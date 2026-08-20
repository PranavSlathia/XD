import Observation
import SwiftUI

@MainActor
@Observable
public final class InstrumentTheme {
    public let canvas = Color(hex: 0x101211)
    public let sidebar = Color(hex: 0x141716)
    public let panel = Color(hex: 0x191C1B)
    public let raised = Color(hex: 0x1E2220)
    public let selected = Color(hex: 0x292C2B)
    public let line = Color.white.opacity(0.11)
    public let label = Color(hex: 0xE9EBE8)
    public let secondaryLabel = Color(hex: 0x9EA49F)
    public let tertiaryLabel = Color(hex: 0x707671)
    public let amber = Color(hex: 0xE5AA25)
    public let green = Color(hex: 0x69BE58)
    public let blue = Color(hex: 0x5A94C4)
    public let red = Color(hex: 0xE2615A)

    public init() {}

    public func stateColor(_ state: GateState) -> Color {
        switch state {
        case .pass: green
        case .fail: red
        case .pending: amber
        }
    }

    public func laneColor(_ lane: AssetLane) -> Color {
        lane == .name ? green : blue
    }

    public func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

public extension Color {
    init(hex: UInt, opacity: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}

public struct InstrumentButtonStyle: ButtonStyle {
    public enum Tone { case neutral, primary, destructive }

    @Environment(InstrumentTheme.self) private var theme
    private let tone: Tone

    public init(tone: Tone = .neutral) {
        self.tone = tone
    }

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(foreground)
            .frame(maxWidth: .infinity, minHeight: 42)
            .padding(.horizontal, 14)
            .background(background.opacity(configuration.isPressed ? 0.72 : 1))
            .overlay {
                RoundedRectangle(cornerRadius: 4)
                    .stroke(border, lineWidth: 1)
            }
            .clipShape(RoundedRectangle(cornerRadius: 4))
            .contentShape(Rectangle())
    }

    private var foreground: Color {
        switch tone {
        case .neutral: theme.label
        case .primary: .white
        case .destructive: theme.red
        }
    }

    private var background: Color {
        switch tone {
        case .neutral, .destructive: theme.raised
        case .primary: theme.green.opacity(0.55)
        }
    }

    private var border: Color {
        switch tone {
        case .neutral: theme.line
        case .primary: theme.green.opacity(0.68)
        case .destructive: theme.red.opacity(0.45)
        }
    }
}

public struct InstrumentPanel<Content: View>: View {
    @Environment(InstrumentTheme.self) private var theme
    private let content: Content

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    public var body: some View {
        content
            .background(theme.panel)
            .overlay {
                RoundedRectangle(cornerRadius: 4)
                    .stroke(theme.line, lineWidth: 1)
            }
            .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}

struct StatusLamp: View {
    @Environment(InstrumentTheme.self) private var theme
    let color: Color
    let label: String

    var body: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
                .accessibilityHidden(true)
            Text(label)
                .foregroundStyle(theme.secondaryLabel)
        }
        .accessibilityElement(children: .combine)
    }
}
