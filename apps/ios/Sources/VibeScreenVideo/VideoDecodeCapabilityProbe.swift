import CoreMedia
import VideoToolbox
import VibeScreenCore
import VibeScreenProtocol

public enum VideoDecodeCapabilityProbe {
    public static func probe(
        av1DecoderImplementationAvailable: Bool = VideoDecodeImplementationSupport.hasDecodeImplementation(for: .av1)
    ) -> VideoDecodeCapabilitySnapshot {
        VideoDecodeCapabilitySnapshot(
            h264HardwareDecoderAvailable: VTIsHardwareDecodeSupported(kCMVideoCodecType_H264),
            hevcHardwareDecoderAvailable: VTIsHardwareDecodeSupported(kCMVideoCodecType_HEVC),
            av1HardwareDecoderAvailable: VTIsHardwareDecodeSupported(kCMVideoCodecType_AV1),
            av1DecoderImplementationAvailable: av1DecoderImplementationAvailable
        )
    }
}
