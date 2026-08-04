import Foundation

public enum AnnexB {
    public static func nalUnits(in data: Data) -> [Data] {
        let bytes = [UInt8](data)
        var starts: [(offset: Int, prefixLength: Int)] = []
        var index = 0
        while index + 3 <= bytes.count {
            if index + 4 <= bytes.count,
               bytes[index] == 0, bytes[index + 1] == 0,
               bytes[index + 2] == 0, bytes[index + 3] == 1 {
                starts.append((index, 4))
                index += 4
            } else if bytes[index] == 0, bytes[index + 1] == 0, bytes[index + 2] == 1 {
                starts.append((index, 3))
                index += 3
            } else {
                index += 1
            }
        }

        return starts.enumerated().compactMap { item in
            let start = item.element.offset + item.element.prefixLength
            let end = item.offset + 1 < starts.count ? starts[item.offset + 1].offset : bytes.count
            guard start < end else { return nil }
            return Data(bytes[start..<end])
        }
    }

    public static func lengthPrefixedSample(from data: Data) -> Data {
        nalUnits(in: data).reduce(into: Data()) { result, unit in
            var length = UInt32(unit.count).bigEndian
            withUnsafeBytes(of: &length) { result.append(contentsOf: $0) }
            result.append(unit)
        }
    }
}
