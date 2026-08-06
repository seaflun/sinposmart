import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

RowLayout {
    id: dutyOperationBar
    required property var backend
    required property var hostWindow
    property int modeIndex: 0
    signal modeChangeRequested(int index)

    Layout.preferredWidth: implicitWidth
    Layout.preferredHeight: Design.appTitleMenuButtonHeight
    implicitWidth: modeMenuButton.implicitWidth + systemMenuButton.implicitWidth
                   + windowMenuButton.implicitWidth + (spacing * 2)
    visible: dutyOperationBar.backend.sessionController.isLoggedIn
    spacing: Design.appTitleMenuSpacing
    readonly property bool hasOpenMenu: modeMenu.visible || systemMenu.visible || windowMenu.visible

    function closeOpenMenus() {
        const wasOpen = hasOpenMenu
        modeMenu.close()
        systemMenu.close()
        windowMenu.close()
        return wasOpen
    }

    function openModeMenu() {
        if (systemMenu.visible)
            systemMenu.close()
        if (windowMenu.visible)
            windowMenu.close()
        modeMenu.popup(modeMenuButton, 0, modeMenuButton.height + 2)
    }

    function toggleModeMenu() {
        if (modeMenu.visible) {
            modeMenu.close()
            return
        }
        dutyOperationBar.openModeMenu()
    }

    function openSystemMenu() {
        if (modeMenu.visible)
            modeMenu.close()
        if (windowMenu.visible)
            windowMenu.close()
        systemMenu.popup(systemMenuButton, 0, systemMenuButton.height + 2)
    }

    function toggleSystemMenu() {
        if (systemMenu.visible) {
            systemMenu.close()
            return
        }
        dutyOperationBar.openSystemMenu()
    }

    function openWindowMenu() {
        if (modeMenu.visible)
            modeMenu.close()
        if (systemMenu.visible)
            systemMenu.close()
        windowMenu.popup(windowMenuButton, 0, windowMenuButton.height + 2)
    }

    function toggleWindowMenu() {
        if (windowMenu.visible) {
            windowMenu.close()
            return
        }
        dutyOperationBar.openWindowMenu()
    }

    component CommandMenuItem: MenuItem {
        id: commandMenuItem
        property bool currentMode: false
        implicitWidth: 168
        implicitHeight: 34
        leftPadding: 12
        rightPadding: 12
        hoverEnabled: !currentMode

        contentItem: Text {
            text: commandMenuItem.text
            color: commandMenuItem.currentMode ? Design.titleMenuCurrentText
                   : commandMenuItem.enabled ? Design.text
                   : Design.muted
            font.pixelSize: Design.bodySize
            font.weight: commandMenuItem.currentMode ? Font.DemiBold : Font.Normal
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: Design.radiusSmall
            color: commandMenuItem.currentMode ? Design.titleMenuCurrentSurface
                   : commandMenuItem.highlighted ? Design.comboHover
                   : Design.transparent
            border.width: Design.noBorderWidth
        }
    }

    AppleButton {
        id: modeMenuButton
        objectName: "modeMenuButton"
        property bool closesOpenMenu: false
        implicitWidth: Design.appTitleMenuButtonWidth
        implicitHeight: Design.appTitleMenuButtonHeight
        leftPadding: 8
        rightPadding: 8
        text: "模式"
        tone: "menu"
        instantFeedback: true
        showFocusRing: false
        focusPolicy: Qt.NoFocus
        scale: 1
        onPressed: closesOpenMenu = modeMenu.visible
        onClicked: {
            if (closesOpenMenu) {
                closesOpenMenu = false
                modeMenu.close()
                return
            }
            dutyOperationBar.toggleModeMenu()
        }
        onHoveredChanged: {
            if (hovered && (systemMenu.visible || windowMenu.visible))
                dutyOperationBar.openModeMenu()
        }
    }

    AppleButton {
        id: systemMenuButton
        objectName: "systemMenuButton"
        property bool closesOpenMenu: false
        implicitWidth: Design.appTitleMenuButtonWidth
        implicitHeight: Design.appTitleMenuButtonHeight
        leftPadding: 8
        rightPadding: 8
        text: "系統"
        tone: "menu"
        instantFeedback: true
        showFocusRing: false
        focusPolicy: Qt.NoFocus
        scale: 1
        onPressed: closesOpenMenu = systemMenu.visible
        onClicked: {
            if (closesOpenMenu) {
                closesOpenMenu = false
                systemMenu.close()
                return
            }
            dutyOperationBar.toggleSystemMenu()
        }
        onHoveredChanged: {
            if (hovered && (modeMenu.visible || windowMenu.visible))
                dutyOperationBar.openSystemMenu()
        }
    }

    AppleButton {
        id: windowMenuButton
        objectName: "windowMenuButton"
        property bool closesOpenMenu: false
        implicitWidth: Design.appTitleMenuButtonWidth
        implicitHeight: Design.appTitleMenuButtonHeight
        leftPadding: 8
        rightPadding: 8
        text: "視窗"
        tone: "menu"
        instantFeedback: true
        showFocusRing: false
        focusPolicy: Qt.NoFocus
        scale: 1
        onPressed: closesOpenMenu = windowMenu.visible
        onClicked: {
            if (closesOpenMenu) {
                closesOpenMenu = false
                windowMenu.close()
                return
            }
            dutyOperationBar.toggleWindowMenu()
        }
        onHoveredChanged: {
            if (hovered && (modeMenu.visible || systemMenu.visible))
                dutyOperationBar.openWindowMenu()
        }
    }

    Menu {
        id: modeMenu
        objectName: "modeCommandMenu"
        parent: dutyOperationBar.hostWindow.contentItem
        modal: false
        closePolicy: Popup.CloseOnReleaseOutside | Popup.CloseOnEscape
        implicitWidth: 180
        padding: 6

        background: Rectangle {
            radius: Design.radiusMedium
            color: Design.panel
            border.width: Design.borderWidth
            border.color: Design.border
        }

        CommandMenuItem {
            objectName: "dutyModeTab"
            text: "值班模式"
            currentMode: dutyOperationBar.modeIndex === 0
            enabled: !currentMode
            onTriggered: dutyOperationBar.modeChangeRequested(0)
        }
        CommandMenuItem {
            objectName: "auditModeTab"
            text: "審核模式"
            currentMode: dutyOperationBar.modeIndex === 1
            enabled: !currentMode
            onTriggered: dutyOperationBar.modeChangeRequested(1)
        }
    }

    Menu {
        id: systemMenu
        objectName: "systemCommandMenu"
        parent: dutyOperationBar.hostWindow.contentItem
        modal: false
        closePolicy: Popup.CloseOnReleaseOutside | Popup.CloseOnEscape
        implicitWidth: 180
        padding: 6

        background: Rectangle {
            radius: Design.radiusMedium
            color: Design.panel
            border.width: Design.borderWidth
            border.color: Design.border
        }

        CommandMenuItem {
            objectName: "checkForUpdatesMenuItem"
            text: dutyOperationBar.backend.updateController.isChecking ? "檢查中…" : "檢查更新"
            enabled: !dutyOperationBar.backend.updateController.isChecking
            onTriggered: dutyOperationBar.backend.updateController.check()
        }
        CommandMenuItem {
            objectName: "exportIssuePackageMenuItem"
            text: "匯出問題包"
            onTriggered: dutyOperationBar.backend.exportIssuePackage()
        }
    }

    Menu {
        id: windowMenu
        objectName: "windowCommandMenu"
        parent: dutyOperationBar.hostWindow.contentItem
        modal: false
        closePolicy: Popup.CloseOnReleaseOutside | Popup.CloseOnEscape
        implicitWidth: 180
        padding: 6

        background: Rectangle {
            radius: Design.radiusMedium
            color: Design.panel
            border.width: Design.borderWidth
            border.color: Design.border
        }

        CommandMenuItem {
            objectName: "hideToBackgroundMenuItem"
            text: "縮小到背景"
            onTriggered: dutyOperationBar.backend.trayController.hideWindow()
        }
        CommandMenuItem {
            objectName: "logoutMenuItem"
            text: "登出"
            onTriggered: dutyOperationBar.backend.sessionController.logout()
        }
        MenuSeparator {}
        CommandMenuItem {
            objectName: "quitApplicationMenuItem"
            text: "結束程式"
            onTriggered: dutyOperationBar.backend.trayController.requestQuit()
        }
    }
}
