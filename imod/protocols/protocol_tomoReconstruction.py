# *****************************************************************************
# *
# * Authors:     Federico P. de Isidro Gomez (fp.deisidro@cnb.csic.es) [1]
# *
# * [1] Centro Nacional de Biotecnologia, CSIC, Spain
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# *****************************************************************************

import os

from pyworkflow import BETA
from pyworkflow.object import Set
import pyworkflow.protocol.params as params
from tomo.objects import Tomogram

from .. import Plugin
from .protocol_base import ProtImodBase


class ProtImodTomoReconstruction(ProtImodBase):
    """
    Tomogram reconstruction procedure based on the IMOD procedure.

    More info:
        https://bio3d.colorado.edu/imod/doc/man/tilt.html
    """

    _label = 'Tomo reconstruction'
    _devStatus = BETA

    # -------------------------- DEFINE param functions -----------------------
    def _defineParams(self, form):
        form.addSection('Input')

        form.addParam('inputSetOfTiltSeries',
                      params.PointerParam,
                      pointerClass='SetOfTiltSeries',
                      important=True,
                      label='Input set of tilt-series')

        form.addParam('tomoThickness',
                      params.FloatParam,
                      default=1000,
                      label='Tomogram thickness (voxels)',
                      important=True,
                      display=params.EnumParam.DISPLAY_HLIST,
                      help='Size in voxels of the tomogram in the z '
                           'axis (beam direction).')

        form.addParam('tomoShiftX',
                      params.FloatParam,
                      default=0,
                      label='Tomogram shift in X',
                      display=params.EnumParam.DISPLAY_HLIST,
                      help='This entry allows one to shift the reconstructed '
                           'slice in X before it is output.  If the X shift '
                           'is positive, the slice will be shifted to the '
                           'right, and the output will contain the left part '
                           'of the whole potentially reconstructable area.')

        form.addParam('tomoShiftZ',
                      params.FloatParam,
                      default=0,
                      label='Tomogram shift in Z',
                      display=params.EnumParam.DISPLAY_HLIST,
                      help='This entry allows one to shift the reconstructed '
                           'slice in Z before it is output. If the Z '
                           'shift is positive, the slice is shifted upward. '
                           'The Z entry is optional and defaults to 0 '
                           'when omitted.')

        form.addParam('angleOffset',
                      params.FloatParam,
                      default=0,
                      label='Angle offset',
                      display=params.EnumParam.DISPLAY_HLIST,
                      help='Apply an angle offset in degrees to all tilt '
                           'angles. This offset positively rotates the '
                           'reconstructed sections anticlockwise.')

        form.addParam('tiltAxisOffset',
                      params.FloatParam,
                      default=0,
                      label='Tilt axis offset',
                      display=params.EnumParam.DISPLAY_HLIST,
                      help='Apply an offset to the tilt axis in a stack of '
                           'full-sized projection images, cutting the '
                           'X-axis at  NX/2. + offset instead of NX/2. The '
                           'DELXX entry is optional and defaults to 0 '
                           'when omitted.')

        form.addParam('fakeInteractionsSIRT',
                      params.IntParam,
                      default=0,
                      label='Iterations of a SIRT-like equivalent filter',
                      display=params.EnumParam.DISPLAY_HLIST,
                      expertLevel=params.LEVEL_ADVANCED,
                      help='Modify the radial filter to produce a '
                           'reconstruction equivalent to the one produced by '
                           'the given number of iterations of SIRT. The '
                           'Gaussian filter is applied at the high-frequency '
                           'end of the filter. The functioning of this filter '
                           'is described in: \n\t'
                           'https://bio3d.colorado.edu/imod/doc/man/tilt.html')

        groupRadialFrequencies = form.addGroup('Radial filtering',
                                               help='This entry controls low-pass '
                                                    'filtering with the radial weighting '
                                                    'function. The radial weighting '
                                                    'function is linear away from the '
                                                    'origin out to the distance in '
                                                    'reciprocal space specified by the '
                                                    'first value, followed by a Gaussian '
                                                    'fall-off determined by the '
                                                    'second value.',
                                               expertLevel=params.LEVEL_ADVANCED)

        groupRadialFrequencies.addParam('radialFirstParameter',
                                        params.FloatParam,
                                        default=0.35,
                                        label='First parameter',
                                        help='Linear region value')

        groupRadialFrequencies.addParam('radialSecondParameter',
                                        params.FloatParam,
                                        default=0.035,
                                        label='Second parameter',
                                        help='Gaussian fall-off parameter')

        form.addHidden(params.USE_GPU,
                       params.BooleanParam,
                       default=True,
                       label="Use GPU for execution",
                       help="This protocol has both CPU and GPU implementation. "
                            "Select the one you want to use.")

        form.addHidden(params.GPU_LIST,
                       params.StringParam,
                       default='0',
                       expertLevel=params.LEVEL_ADVANCED,
                       label="Choose GPU IDs",
                       help="GPU ID. To pick the best available one set 0. "
                            "For a specific GPU set its number ID "
                            "(starting from 1).")

    # -------------------------- INSERT steps functions -----------------------
    def _insertAllSteps(self):
        for ts in self.inputSetOfTiltSeries.get():
            self._insertFunctionStep(self.convertInputStep, ts.getObjId())
            self._insertFunctionStep(self.computeReconstructionStep, ts.getObjId())
            self._insertFunctionStep(self.createOutputStep, ts.getObjId())
        self._insertFunctionStep(self.closeOutputSetsStep)

    # --------------------------- STEPS functions -----------------------------
    def convertInputStep(self, tsObjId):
        # Considering swapXY is required to make tilt axis vertical
        super().convertInputStep(tsObjId, doSwap=True)

    def computeReconstructionStep(self, tsObjId):
        ts = self.inputSetOfTiltSeries.get()[tsObjId]
        tsId = ts.getTsId()

        firstItem = ts.getFirstItem()

        extraPrefix = self._getExtraPath(tsId)
        tmpPrefix = self._getTmpPath(tsId)

        paramsTilt = {
            'InputProjections': os.path.join(tmpPrefix, firstItem.parseFileName()),
            'OutputFile': os.path.join(tmpPrefix, firstItem.parseFileName(extension=".rec")),
            'TiltFile': os.path.join(tmpPrefix, firstItem.parseFileName(extension=".tlt")),
            'Thickness': self.tomoThickness.get(),
            'FalloffIsTrueSigma': 1,
            'Radial': str(self.radialFirstParameter.get()) + "," + str(self.radialSecondParameter.get()),
            'Shift': str(self.tomoShiftX.get()) + "," + str(self.tomoShiftZ.get()),
            'Offset': str(self.angleOffset.get()) + "," + str(self.tiltAxisOffset.get()),
        }

        argsTilt = "-InputProjections %(InputProjections)s " \
                   "-OutputFile %(OutputFile)s " \
                   "-TILTFILE %(TiltFile)s " \
                   "-THICKNESS %(Thickness)d " \
                   "-FalloffIsTrueSigma %(FalloffIsTrueSigma)d " \
                   "-RADIAL %(Radial)s " \
                   "-SHIFT %(Shift)s " \
                   "-OFFSET %(Offset)s " \
                   "-MODE 1 " \
                   "-PERPENDICULAR " \
                   "-AdjustOrigin "

        if self.fakeInteractionsSIRT.get() != 0:
            paramsTilt.update({
                'FakeSIRTInteractions': self.fakeInteractionsSIRT.get()
            })
            argsTilt += "-FakeSIRTiterations %(FakeSIRTInteractions)d "

        # Excluded views
        excludedViews = ts.getExcludedViewsIndex(caster=str)
        if len(excludedViews):
            argsTilt += f"-EXCLUDELIST2 {','.join(excludedViews)} "

        if self.usesGpu():
            argsTilt += f"-UseGPU {self.getGpuList()[0]} " \
                        "-ActionIfGPUFails 2,2 "

        Plugin.runImod(self, 'tilt', argsTilt % paramsTilt)

        paramsTrimVol = {
            'input': os.path.join(tmpPrefix, firstItem.parseFileName(extension=".rec")),
            'output': os.path.join(extraPrefix, firstItem.parseFileName(extension=".mrc")),
            'options': "-rx "
        }

        argsTrimvol = "%(options)s " \
                      "%(input)s " \
                      "%(output)s "

        Plugin.runImod(self, 'trimvol', argsTrimvol % paramsTrimVol)

    def createOutputStep(self, tsObjId):
        ts = self.inputSetOfTiltSeries.get()[tsObjId]
        tsId = ts.getTsId()
        firstItem = ts.getFirstItem()

        extraPrefix = self._getExtraPath(tsId)

        output = self.getOutputSetOfTomograms(self.inputSetOfTiltSeries.get())

        newTomogram = Tomogram()
        newTomogram.setLocation(os.path.join(extraPrefix,
                                             firstItem.parseFileName(extension=".mrc")))
        newTomogram.setTsId(tsId)
        newTomogram.setSamplingRate(ts.getSamplingRate())
        # Set default tomogram origin
        newTomogram.setOrigin(newOrigin=None)
        newTomogram.setAcquisition(ts.getAcquisition())

        output.append(newTomogram)
        output.update(newTomogram)
        output.write()
        self._store()

    def closeOutputSetsStep(self):
        self.Tomograms.setStreamState(Set.STREAM_CLOSED)
        self.Tomograms.write()
        self._store()

    # --------------------------- INFO functions ----------------------------
    def _summary(self):
        summary = []
        if self.Tomograms:
            summary.append("Input tilt-series: %d\nTomograms reconstructed: %d"
                           % (self.inputSetOfTiltSeries.get().getSize(),
                              self.Tomograms.getSize()))
        else:
            summary.append("Outputs are not ready yet.")
        return summary

    def _methods(self):
        methods = []
        if self.Tomograms:
            methods.append("The reconstruction has been computed for %d "
                           "tilt-series using the IMOD *tilt* command.\n"
                           % (self.Tomograms.getSize()))
        return methods
