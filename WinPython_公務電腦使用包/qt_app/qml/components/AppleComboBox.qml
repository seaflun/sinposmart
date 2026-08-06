pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../styles"

ComboBox {
    id: appleCombo
    property bool compact: false
    implicitHeight: compact ? Design.toolCompactControlHeight : 34
    leftPadding: 10
    rightPadding: 34
    topPadding: 0
    bottomPadding: 0
    font.pixelSize: Design.bodySize
    hoverEnabled: true

    contentItem: Text {
        width: appleCombo.availableWidth
        height: appleCombo.availableHeight
        leftPadding: 0
        rightPadding: 0
        text: appleCombo.displayText
        color: appleCombo.enabled ? Design.text : Design.muted
        font: appleCombo.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    delegate: ItemDelegate {
        id: comboDelegate
        required property int index
        required property var modelData
        width: appleCombo.width
        implicitHeight: appleCombo.compact ? Design.toolCompactControlHeight : 34
        leftPadding: 10
        rightPadding: 10
        highlighted: appleCombo.highlightedIndex === comboDelegate.index
        hoverEnabled: appleCombo.hoverEnabled

        contentItem: Text {
            text: String(comboDelegate.modelData ?? "")
            color: appleCombo.enabled ? Design.text : Design.muted
            font: appleCombo.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: Design.radiusSmall
            color: comboDelegate.down ? Design.comboSelected
                 : comboDelegate.hovered ? Design.comboHover
                 : Design.transparent
        }
    }
    indicator: Item {
        x: appleCombo.width - width - 8
        width: 24
        height: appleCombo.height
        rotation: appleCombo.popup.visible ? 180 : 0
        property color arrowColor: !appleCombo.enabled ? Design.muted
                                   : appleCombo.popup.visible || appleCombo.hovered || appleCombo.down
                                     ? Design.blue : Design.secondaryText

        onArrowColorChanged: arrowCanvas.requestPaint()

        Behavior on rotation {
            NumberAnimation { duration: Design.buttonFeedbackDuration; easing.type: Easing.OutCubic }
        }
        Canvas {
            id: arrowCanvas
            anchors.centerIn: parent
            width: Design.comboArrowWidth
            height: Design.comboArrowHeight

            onPaint: {
                const context = getContext("2d")
                context.clearRect(0, 0, width, height)
                context.strokeStyle = parent.arrowColor
                context.lineWidth = Design.comboArrowStrokeWidth
                context.lineCap = "round"
                context.lineJoin = "round"
                context.beginPath()
                context.moveTo(Design.comboArrowInset, Design.comboArrowInset)
                context.lineTo(width / 2, height - Design.comboArrowInset)
                context.lineTo(width - Design.comboArrowInset, Design.comboArrowInset)
                context.stroke()
            }
        }
    }
    popup: Popup {
        y: appleCombo.height + 5
        width: appleCombo.width
        implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, 224)
        padding: 4

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: appleCombo.popup.visible ? appleCombo.delegateModel : null
            currentIndex: appleCombo.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
        background: Rectangle {
            radius: Design.radiusMedium
            color: Design.panel
            border.width: Design.borderWidth
            border.color: Design.border
        }
    }
    background: Rectangle {
        radius: Design.radius
        color: !appleCombo.enabled ? Design.softAction
             : appleCombo.down ? Design.comboSelected
             : appleCombo.hovered ? Design.comboHover
             : Design.panel
        border.width: appleCombo.activeFocus ? Design.focusBorderWidth : Design.borderWidth
        border.color: appleCombo.activeFocus || appleCombo.down || appleCombo.hovered
                      ? Design.blue : Design.border
    }
}
