#!/usr/bin/env swift
// docs/gen_comparison.swift — render the README comparison grid cells (32×32 PNGs).
// Usage: swift docs/gen_comparison.swift [emojiswap-root [output-dir]]
//   emojiswap-root  default: ../emojiswap  (sibling of emojifonts)
//   output-dir      default: docs/comparison
import AppKit
import CoreText

let args = CommandLine.arguments
let SWAP = args.count > 1 ? args[1] : "\(FileManager.default.currentDirectoryPath)/../emojiswap"
let OUT  = args.count > 2 ? args[2] : "docs/comparison"
let PX   = 32    // final cell size

// ---------------------------------------------------------------------------
// Categories: (category-name, [(emoji-string, short-label)])
// 3 iconic emoji per category
// ---------------------------------------------------------------------------
let CATS: [(String, [(String, String)])] = [
    ("smileys",  [("😀","1f600"), ("😂","1f602"), ("😍","1f60d")]),
    ("people",   [("👋","1f44b"), ("🤔","1f914"), ("💪","1f4aa")]),
    ("animals",  [("🐶","1f436"), ("🐱","1f431"), ("🐼","1f43c")]),
    ("food",     [("🍕","1f355"), ("🍔","1f354"), ("🍣","1f363")]),
    ("travel",   [("🚗","1f697"), ("✈","2708"),  ("🚀","1f680")]),
    ("activity", [("⚽","26bd"), ("🎮","1f3ae"), ("🎸","1f3b8")]),
    ("objects",  [("💡","1f4a1"), ("📱","1f4f1"), ("🎁","1f381")]),
    ("symbols",  [("❤","2764"),        ("⭐","2b50"), ("🔥","1f525")]),
    ("flags",    [("🏁","1f3c1"), ("🏴","1f3f4"), ("🚩","1f6a9")]),
    ("country",  [("🇺🇸","1f1fa-1f1f8"), ("🇯🇵","1f1ef-1f1f5"), ("🇬🇧","1f1ec-1f1e7")]),
]

// ---------------------------------------------------------------------------
// Font sets: (id, font-file-path)
// ---------------------------------------------------------------------------
let SETS: [(String, String)] = [
    ("apple",       "\(SWAP)/system-font/backup/Apple Color Emoji.ttc.orig"),
    ("noto",        "\(SWAP)/fonts/noto.ttf"),
    ("twemoji",     "\(SWAP)/fonts/twemoji.ttf"),
    ("openmoji",    "\(SWAP)/fonts/openmoji.ttf"),
    ("blobmoji",    "\(SWAP)/fonts/blobmoji.ttf"),
    ("tossface",    "\(SWAP)/fonts/tossface.ttf"),
    ("fluent",      "\(SWAP)/fonts/fluent.ttf"),
    ("fluent-flat", "\(SWAP)/fonts/fluent-flat.ttf"),
    ("emojitwo",    "\(SWAP)/fonts/emojitwo.ttf"),
    ("noto-mono",   "\(SWAP)/fonts/noto-mono.ttf"),
    ("fluent-mono", "\(SWAP)/fonts/fluent-mono.ttf"),
]

// True iff every run in `line` came from `font` (no Core Text fallback).
func lineUsesOnly(_ font: CTFont, _ line: CTLine) -> Bool {
    guard let runs = CTLineGetGlyphRuns(line) as? [CTRun], !runs.isEmpty else { return false }
    let want = CTFontCopyPostScriptName(font) as String
    for run in runs {
        guard let used = (CTRunGetAttributes(run) as NSDictionary)[kCTFontAttributeName as String] else { return false }
        if (CTFontCopyPostScriptName(used as! CTFont) as String) != want { return false }
    }
    return true
}

// Render `ch` in `font` centred in a PX×PX bitmap; returns nil if the glyph
// isn't in the font (Core Text fell back to another face).
func render(_ ch: String, font: CTFont) -> CGImage? {
    let attr = CFAttributedStringCreate(nil, ch as CFString,
                                        [kCTFontAttributeName: font] as CFDictionary)!
    let line = CTLineCreateWithAttributedString(attr)
    guard lineUsesOnly(font, line) else { return nil }
    let n = PX
    guard let ctx = CGContext(data: nil, width: n, height: n,
                              bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { return nil }

    // First pass: get image bounds to fit/centre art.
    ctx.textPosition = .zero
    let ib = CTLineGetImageBounds(line, ctx)
    guard ib.width > 1, ib.height > 1 else { return ctx.makeImage() }
    let scale = min(1, CGFloat(n) * 0.94 / max(ib.width, ib.height))
    ctx.translateBy(x: CGFloat(n) / 2, y: CGFloat(n) / 2)
    ctx.scaleBy(x: scale, y: scale)
    ctx.textPosition = CGPoint(x: -ib.midX, y: -ib.midY)
    CTLineDraw(line, ctx)
    return ctx.makeImage()
}

func pngData(_ img: CGImage) -> Data? {
    NSBitmapImageRep(cgImage: img).representation(using: .png, properties: [:])
}

let fm = FileManager.default
var written = 0, skipped = 0, missing = 0

for (setId, fontPath) in SETS {
    guard fm.fileExists(atPath: fontPath) else { print("⚠️  font not found: \(fontPath)"); continue }
    guard let descs = CTFontManagerCreateFontDescriptorsFromURL(URL(fileURLWithPath: fontPath) as CFURL) as? [CTFontDescriptor],
          let d = descs.first
    else { print("⚠️  could not load: \(fontPath)"); continue }

    let fontSize = CGFloat(Double(PX) * 0.82)
    let font = CTFontCreateWithFontDescriptor(d, fontSize, nil)
    let dir = "\(OUT)/\(setId)"
    try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)

    for (_, pairs) in CATS {
        for (ch, key) in pairs {
            let dest = "\(dir)/\(key).png"
            if let img = render(ch, font: font), let data = pngData(img) {
                fm.createFile(atPath: dest, contents: data)
                written += 1
            } else {
                missing += 1   // font lacks this emoji — no file written (cell stays blank)
            }
        }
    }
    print("  \(setId): done")
}

print("\nwrote \(written) cells, \(missing) missing (font lacks glyph), \(skipped) sets skipped")
print("output: \(OUT)/")
