import CoreImage
import CoreVideo
import SwiftUI
import UIKit

struct PixelBufferView: UIViewRepresentable {
    let pixelBuffer: CVPixelBuffer?

    func makeUIView(context: Context) -> PixelBufferUIView {
        PixelBufferUIView()
    }

    func updateUIView(_ view: PixelBufferUIView, context: Context) {
        view.display(pixelBuffer)
    }
}

final class PixelBufferUIView: UIView {
    private let context = CIContext(options: [.cacheIntermediates: false])

    override class var layerClass: AnyClass { CALayer.self }

    func display(_ pixelBuffer: CVPixelBuffer?) {
        guard let pixelBuffer else {
            layer.contents = nil
            return
        }
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = context.createCGImage(image, from: image.extent) else { return }
        layer.contents = cgImage
        layer.contentsGravity = .resizeAspect
    }
}
