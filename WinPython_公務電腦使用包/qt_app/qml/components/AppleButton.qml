import QtQuick
import QtQuick.Controls
import "../styles"

Button {
    id: appleButton
    property string tone: "neutral"
    property bool selectedState: false
    property bool emphasizedBorder: false
    // 標題列控制鈕需要即時回饋，避免游標進出時的色彩漸變造成閃爍感。
    property bool instantFeedback: false
    property bool showFocusRing: true
    property string iconKind: ""
    property bool iconToggled: false
    property real cornerRadius: Design.radius
    property color fillColor: tone === "primary" ? Design.blue
                            : tone === "success" ? Design.successSurface
                            : tone === "successStrong" ? Design.successAction
                            : tone === "danger" ? Design.panel
                            : tone === "dangerFilled" ? Design.dangerFill
                            : tone === "warning" || tone === "warningStrong" ? Design.warningSurface
                            : tone === "review" ? Design.reviewSurface
                            : tone === "monthly" ? Design.monthlySurface
                            : tone === "info" || tone === "infoStrong" ? Design.comboButton
                            : tone === "windowClose" || tone === "windowControl" ? Design.transparent
                            : tone === "menu" ? Design.transparent
                            : tone === "ghost" ? Design.transparent
                            : tone === "neutralStrong" ? Design.softActionHover
                            : Design.softAction
    property color hoverColor: tone === "primary" ? Design.blueHover
                             : tone === "success" ? Design.successHover
                             : tone === "successStrong" ? Design.successHeading
                             : tone === "danger" ? Design.dangerSurface
                             : tone === "dangerFilled" ? Design.dangerStrong
                             : tone === "warning" || tone === "warningStrong" ? Design.warningHover
                             : tone === "review" ? Design.reviewHover
                             : tone === "monthly" ? Design.monthlyHover
                             : tone === "info" || tone === "infoStrong" ? Design.comboBorder
                             : tone === "windowClose" ? Design.dangerFill
                             : tone === "windowControl" ? Design.appWindowControlHover
                             : tone === "menu" ? Design.titleMenuHover
                             : tone === "ghost" ? Design.monthlySurface
                             : tone === "neutralStrong" ? Design.neutralActionHover
                             : Design.softActionHover
    property color strokeColor: emphasizedBorder ? activeStrokeColor
                              : tone === "primary" || tone === "successStrong" || tone === "dangerFilled" || tone === "windowClose" || tone === "windowControl" || tone === "menu" || tone === "ghost" ? Design.transparent
                              : tone === "success" ? Design.successBorder
                              : tone === "danger" ? Design.dangerBorder
                              : tone === "warningStrong" ? Design.warningStrongBorder
                              : tone === "warning" ? Design.warningBorder
                              : tone === "monthly" ? Design.monthlyBorder
                              : tone === "infoStrong" ? Design.infoBorder
                              : tone === "info" ? Design.comboBorder
                              : tone === "neutralStrong" ? Design.neutralActionHover
                              : Design.border
    property color textColor: tone === "primary" ? Design.panel
                            : tone === "successStrong" ? Design.panel
                            : tone === "success" ? Design.successText
                            : tone === "danger" ? Design.redHover
                            : tone === "dangerFilled" ? Design.panel
                            : tone === "warning" || tone === "warningStrong" ? Design.warningText
                            : tone === "review" ? Design.reviewText
                            : tone === "monthly" ? Design.monthlyText
                            : tone === "info" || tone === "infoStrong" ? Design.blueHover
                            : tone === "windowClose" || tone === "windowControl" || tone === "menu" || tone === "ghost" || tone === "neutralStrong" ? Design.controlText
                            : Design.text
    property color disabledFillColor: tone === "dangerFilled" ? Design.dangerDisabled : Design.softAction
    property color visualFillColor: !enabled ? disabledFillColor
                                    : down || selectedState || hovered ? hoverColor
                                    : fillColor
    property color foregroundColor: !enabled ? Design.muted
                                   : tone === "windowClose" && (hovered || down) ? Design.panel
                                   : textColor
    property color activeStrokeColor: tone === "primary" ? Design.blueHover
                                      : tone === "success" || tone === "successStrong" ? Design.successHeading
                                      : tone === "danger" || tone === "dangerFilled" ? Design.redHover
                                      : tone === "warning" || tone === "warningStrong" ? Design.warningText
                                      : tone === "review" ? Design.reviewText
                                      : tone === "monthly" ? Design.monthlyText
                                      : tone === "info" || tone === "infoStrong" ? Design.blueHover
                                      : tone === "windowClose" ? Design.redHover
                                      : tone === "windowControl" ? Design.controlText
                                      : tone === "menu" || tone === "ghost" || tone === "neutralStrong" ? Design.controlText
                                      : Design.controlText
    property int strokeWidth: emphasizedBorder ? Design.borderWidth
                             : tone === "primary" || tone === "successStrong" || tone === "dangerFilled" || tone === "windowClose" || tone === "windowControl" || tone === "menu" || tone === "ghost" ? Design.noBorderWidth : Design.borderWidth
    property string disabledHint: ""
    implicitHeight: 40
    leftPadding: 16
    rightPadding: 16
    font.pixelSize: Design.bodySize
    font.weight: Font.DemiBold
    hoverEnabled: true
    scale: down ? 0.98 : 1

    Behavior on scale {
        NumberAnimation {
            duration: appleButton.down ? 0 : Design.buttonFeedbackDuration
            easing.type: Easing.OutCubic
        }
    }

    ToolTip.visible: appleButton.hovered && !appleButton.enabled && appleButton.disabledHint.length > 0
    ToolTip.text: appleButton.disabledHint
    ToolTip.delay: 350
    ToolTip.timeout: 3000

    contentItem: Item {
        implicitWidth: appleButton.iconKind.length === 0
                       ? buttonText.implicitWidth
                       : buttonIcon.implicitWidth
        implicitHeight: appleButton.iconKind.length === 0
                        ? buttonText.implicitHeight
                        : buttonIcon.implicitHeight

        Text {
            id: buttonText
            anchors.fill: parent
            visible: appleButton.iconKind.length === 0
            text: appleButton.text
            color: appleButton.foregroundColor
            font: appleButton.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        Item {
            id: buttonIcon
            anchors.centerIn: parent
            visible: appleButton.iconKind.length > 0
            width: Design.appWindowControlSymbolSize
            height: Design.appWindowControlSymbolSize
            implicitWidth: width
            implicitHeight: height

            Rectangle {
                visible: appleButton.iconKind === "minimize"
                anchors.centerIn: parent
                width: parent.width
                height: Design.appWindowControlSymbolStrokeWidth
                color: appleButton.foregroundColor
            }

            Rectangle {
                visible: appleButton.iconKind === "maximize" && !appleButton.iconToggled
                anchors.centerIn: parent
                width: parent.width
                height: parent.height
                radius: Design.appWindowControlSymbolRadius
                color: Design.transparent
                border.width: Design.appWindowControlSymbolStrokeWidth
                border.color: appleButton.foregroundColor
            }

            Rectangle {
                visible: appleButton.iconKind === "maximize" && appleButton.iconToggled
                x: Design.appWindowControlSymbolStrokeWidth * 2
                y: 0
                width: parent.width - Design.appWindowControlSymbolStrokeWidth * 2
                height: parent.height - Design.appWindowControlSymbolStrokeWidth * 2
                radius: Design.appWindowControlSymbolRadius
                color: Design.transparent
                border.width: Design.appWindowControlSymbolStrokeWidth
                border.color: appleButton.foregroundColor
            }

            Rectangle {
                visible: appleButton.iconKind === "maximize" && appleButton.iconToggled
                x: 0
                y: Design.appWindowControlSymbolStrokeWidth * 2
                width: parent.width - Design.appWindowControlSymbolStrokeWidth * 2
                height: parent.height - Design.appWindowControlSymbolStrokeWidth * 2
                radius: Design.appWindowControlSymbolRadius
                color: Design.transparent
                border.width: Design.appWindowControlSymbolStrokeWidth
                border.color: appleButton.foregroundColor
            }

            Rectangle {
                visible: appleButton.iconKind === "close"
                anchors.centerIn: parent
                width: Design.appWindowControlSymbolStrokeWidth
                height: parent.height + Design.appWindowControlSymbolStrokeWidth * 2
                rotation: 45
                color: appleButton.foregroundColor
            }

            Rectangle {
                visible: appleButton.iconKind === "close"
                anchors.centerIn: parent
                width: Design.appWindowControlSymbolStrokeWidth
                height: parent.height + Design.appWindowControlSymbolStrokeWidth * 2
                rotation: -45
                color: appleButton.foregroundColor
            }
        }
    }
    background: Rectangle {
        radius: appleButton.cornerRadius
        color: appleButton.visualFillColor
        border.width: appleButton.showFocusRing && appleButton.activeFocus
                      ? Design.focusBorderWidth
                      : appleButton.strokeWidth
        border.color: !appleButton.enabled ? appleButton.strokeColor
                      : appleButton.showFocusRing && appleButton.activeFocus ? Design.blue
                      : appleButton.selectedState || appleButton.hovered ? appleButton.activeStrokeColor
                      : appleButton.strokeColor

        Behavior on color {
            ColorAnimation {
                duration: appleButton.instantFeedback ? 0 : Design.buttonColorTransitionDuration
            }
        }
        Behavior on border.color {
            ColorAnimation {
                duration: appleButton.instantFeedback ? 0 : Design.buttonColorTransitionDuration
            }
        }
    }
}
