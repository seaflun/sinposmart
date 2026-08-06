import QtQuick
import QtQuick.Controls
import "../styles"

Control {
    id: sidePanel
    required property var hostWindow
    property bool opened: false
    property bool canClose: true
    property bool hasBeenOpened: false
    visible: opened || (hasBeenOpened && opacity > 0)
    x: hostWindow.dutyMainWidth
    y: Design.appTitleBarHeight + Design.appContentTopSpacing
    width: hostWindow.toolSideWidth
    height: hostWindow.height - Design.appTitleBarHeight
            - Design.appContentTopSpacing - Design.appContentBottomSpacing
    padding: 16
    topPadding: 14
    bottomPadding: 14
    z: 20

    function open() {
        hostWindow.showToolSidePanel(sidePanel)
    }

    function close() {
        hostWindow.hideToolSidePanel(sidePanel)
    }

    onOpenedChanged: {
        if (opened)
            hasBeenOpened = true
    }

    opacity: opened ? 1 : 0
    transform: Translate {
        x: sidePanel.opened ? 0 : -24
        Behavior on x {
            NumberAnimation { duration: Design.sidePanelTransitionDuration; easing.type: Easing.OutCubic }
        }
    }
    Behavior on opacity {
        NumberAnimation { duration: Design.sidePanelTransitionDuration; easing.type: Easing.OutCubic }
    }

    background: Rectangle {
        radius: Design.radiusPanel
        color: Design.sidePanel
        border.width: Design.borderWidth
        border.color: Design.sidePanelBorder
    }
}
