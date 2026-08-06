pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "components"
import "dialogs"
import "pages"
import "styles"

ApplicationWindow {
    id: window
    visible: true
    flags: Qt.Window | Qt.FramelessWindowHint
    width: 550
    height: 320 + Design.appTitleBarHeight
    minimumWidth: 550
    maximumWidth: 550
    minimumHeight: 320 + Design.appTitleBarHeight
    maximumHeight: 320 + Design.appTitleBarHeight
    title: !window.backend.sessionController.isLoggedIn
           ? "登入頁面"
           : modeTabs.currentIndex === 1
             ? "審核模式"
             : "值班模式"
    color: Design.transparent
    palette.window: Design.background
    palette.windowText: Design.text
    palette.base: Design.panel
    palette.alternateBase: Design.softAction
    palette.text: Design.text
    palette.button: Design.panel
    palette.buttonText: Design.text
    palette.highlight: Design.blue
    palette.highlightedText: Design.panel
    palette.placeholderText: Design.muted
    font.pixelSize: Design.bodySize

    onClosing: function(close) {
        if (window.backend.trayController.interceptClose())
            close.accepted = false
    }

    readonly property color ink: Design.text
    readonly property color muted: Design.muted
    readonly property color border: Design.border
    readonly property color accent: Design.blue
    readonly property int dutyMainWidth: 550
    readonly property int auditMainWidth: 780
    readonly property int toolSideWidth: 400
    readonly property int dutyExpandedWidth: 964
    readonly property bool usesCustomTitleBar: true
    readonly property bool canResizeWindow: modeTabs.currentIndex === 1
    property var activeToolSidePanel: null
    property string auditDetailText: ""
    property string errorMessage: ""
    property bool lastHandledLoginState: false
    // qmllint disable unqualified
    readonly property var backend: appController
    // qmllint enable unqualified

    // 無框視窗以透明底承接圓角實體外框，保留原本淺色內容面。
    Rectangle {
        id: appSurface
        anchors.fill: parent
        radius: Design.radiusSheet
        color: Design.background
        border.width: Design.borderWidth
        border.color: Design.border
        z: -1
    }

    Timer {
        id: toolSidePanelCloseTimer
        property var closingPanel: null
        interval: Design.sidePanelTransitionDuration
        repeat: false
        onTriggered: {
            if (window.activeToolSidePanel === closingPanel && !closingPanel.opened) {
                window.activeToolSidePanel = null
                window.syncLegacyWindowGeometry()
            }
        }
    }

    function showAppError(message) {
        const normalized = String(message || "").trim()
        if (!window.backend.sessionController.isLoggedIn) {
            window.errorMessage = ""
            return
        }
        if (normalized.length > 0)
            window.errorMessage = normalized
    }

    function showDutyStatusError(message) {
        const normalized = String(message || "").trim()
        if (!window.backend.sessionController.isLoggedIn || normalized.length === 0)
            return
        window.backend.sessionController.setOperationalStatus(normalized, "warning")
    }

    function shiftSlashDate(value, days) {
        const match = String(value || "").trim().match(/^(\d{4})\/(\d{2})\/(\d{2})$/)
        if (!match)
            return value
        const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
        if (Number.isNaN(date.getTime()))
            return value
        date.setDate(date.getDate() + days)
        const month = String(date.getMonth() + 1).padStart(2, "0")
        const day = String(date.getDate()).padStart(2, "0")
        return date.getFullYear() + "/" + month + "/" + day
    }

    function syncLegacyWindowGeometry() {
        if (modeTabs.currentIndex === 1) {
            if (window.activeToolSidePanel)
                window.activeToolSidePanel.opened = false
            window.activeToolSidePanel = null
            window.minimumWidth = 720
            window.minimumHeight = 560 + Design.appTitleBarHeight
            window.maximumWidth = Design.maximumWindowExtent
            window.maximumHeight = Design.maximumWindowExtent
            window.width = window.auditMainWidth
            window.height = 650 + Design.appTitleBarHeight
            return
        }

        if (!window.backend.sessionController.isLoggedIn && window.activeToolSidePanel) {
            window.activeToolSidePanel.opened = false
            window.activeToolSidePanel = null
        }
        const isLoggedIn = window.backend.sessionController.isLoggedIn
        window.minimumWidth = isLoggedIn ? (window.activeToolSidePanel ? 944 : 530) : window.dutyMainWidth
        window.minimumHeight = (isLoggedIn ? 760 : 320) + Design.appTitleBarHeight
        window.maximumWidth = isLoggedIn ? Design.maximumWindowExtent : window.dutyMainWidth
        window.maximumHeight = isLoggedIn ? Design.maximumWindowExtent : 320 + Design.appTitleBarHeight
        window.width = window.activeToolSidePanel ? window.dutyExpandedWidth : window.dutyMainWidth
        window.height = (isLoggedIn ? 800 : 320) + Design.appTitleBarHeight
    }

    function toggleWindowMaximize() {
        if (!window.canResizeWindow)
            return
        if (window.visibility === Window.Maximized)
            window.showNormal()
        else
            window.showMaximized()
    }

    function positionInAvailableWorkArea() {
        if (!window.screen)
            return
        const screenInfo = window.screen
        const availableX = screenInfo.virtualX
        const availableY = screenInfo.virtualY
        const availableWidth = screenInfo.desktopAvailableWidth
        const availableHeight = screenInfo.desktopAvailableHeight
        window.x = availableX + Math.max(20, Math.round((availableWidth - window.width) / 2))
        window.y = availableY + Math.max(20, Math.round((availableHeight - window.height) / 2))
    }

    function positionDutyWindowAtTopLeft() {
        if (!window.screen)
            return
        const screenInfo = window.screen
        window.x = screenInfo.virtualX + 20
        window.y = screenInfo.virtualY + 20
    }

    function showToolSidePanel(panel) {
        if (!window.backend.sessionController.isLoggedIn || modeTabs.currentIndex !== 0)
            return
        if (window.activeToolSidePanel === panel && panel.opened) {
            window.hideToolSidePanel(panel)
            return
        }
        if (window.activeToolSidePanel)
            window.activeToolSidePanel.opened = false
        toolSidePanelCloseTimer.stop()
        window.activeToolSidePanel = panel
        panel.opened = true
        window.syncLegacyWindowGeometry()
    }

    function hideToolSidePanel(panel) {
        if (panel)
            panel.opened = false
        if (window.activeToolSidePanel === panel) {
            toolSidePanelCloseTimer.closingPanel = panel
            toolSidePanelCloseTimer.restart()
            return
        }
        window.syncLegacyWindowGeometry()
    }

    Connections {
        target: window.backend.sessionController

        function onSavedAccountSelected(_actorNo, userId, password) {
            sessionHeader.userIdText = userId
            sessionHeader.passwordText = password
        }

        function onSessionChanged() {
            const isLoggedIn = window.backend.sessionController.isLoggedIn
            const loginStateChanged = isLoggedIn !== window.lastHandledLoginState
            if (!loginStateChanged)
                return

            window.lastHandledLoginState = isLoggedIn
            window.errorMessage = ""
            if (isLoggedIn)
                sessionHeader.passwordText = ""
            else {
                rescueVideoDialog.close()
                if (modeTabs.currentIndex !== 0)
                    modeTabs.currentIndex = 0
            }
            window.syncLegacyWindowGeometry()
            if (isLoggedIn)
                Qt.callLater(window.positionDutyWindowAtTopLeft)
        }

        function onCredentialSyncConfirmationRequested() {
            actionConfirmations.openCredentialSyncConfirmation()
        }

        function onErrorOccurred(message) {
            window.showAppError(message)
        }
    }


    Connections {
        target: window.backend.restMonthlyController

        function onConfirmationRequested(toolId) {
            actionConfirmations.openRestMonthlyConfirmation()
        }

        function onErrorOccurred(message) {
            window.showAppError(message)
        }
    }

    Connections {
        target: window.backend.dailyVehicleController

        function onConfirmationRequested() {
            actionConfirmations.openDailyVehicleConfirmation()
        }

        function onErrorOccurred(message) {
            window.showAppError(message)
        }
    }

    Connections {
        target: window.backend.dutyController

        function onManualSubmissionConfirmationRequested() {
            actionConfirmations.openManualSubmissionConfirmation()
        }

        function onErrorOccurred(message) {
            window.showDutyStatusError(message)
        }
    }

    Connections {
        target: window.backend.dutyExecutionController

        function onActionFailed(_index, message, _errorCode) {
            window.showDutyStatusError(message)
        }
    }

    Connections {
        target: window.backend.updateController

        function onUpdateReady(_latestVersion) {
            actionConfirmations.openUpdateConfirmation()
        }

        function onCheckCompleted(message) {
            actionConfirmations.openUpdateStatus(message)
        }

        function onErrorOccurred(message) {
            actionConfirmations.openUpdateStatus(message)
        }
    }

    Connections {
        target: window.backend.toolController

        function onErrorOccurred(message) {
            window.showAppError(message)
        }
    }

    Connections {
        target: window.backend.workLogSettingsController

        function onErrorOccurred(message) {
            window.showAppError(message)
        }
    }

    ActionConfirmations {
        id: actionConfirmations
        hostWindow: window
        backend: window.backend
    }

    AppleDialog {
        id: auditDetailDialog
        objectName: "auditDetailDialog"
        anchors.centerIn: parent
        width: Math.min(window.width - 48, 560)
        height: Math.min(window.height - 96, 640)
        modal: true
        title: "審核項目明細"
        standardButtons: Dialog.Close

        ScrollView {
            anchors.fill: parent
            clip: true

            AppleTextArea {
                objectName: "auditDetailTextArea"
                text: window.auditDetailText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: window.ink
                font.pixelSize: Design.labelSize
                background: Rectangle {
                    radius: Design.radiusMedium
                    color: Design.background
                    border.color: window.border
                }
            }
        }
    }

    AccountManagerWindow {
        id: accountManagerWindow
        hostWindow: window
        sessionController: window.backend.sessionController
    }

    FileDialog {
        id: dutyWorkbookDialog
        title: "選擇勤務表 Excel"
        nameFilters: ["Excel files (*.xlsx *.xlsm)"]
        onAccepted: dutySheetDialog.workbookPath = window.backend.dutySheetController.localPath(selectedFile)
    }

    FileDialog {
        id: restWorkbookDialog
        title: "選擇勤務表 Excel"
        nameFilters: ["Excel files (*.xlsx *.xlsm)"]
        onAccepted: window.backend.restMonthlyController.selectRestWorkbook(selectedFile)
    }

    RescueVideoWindow {
        id: rescueVideoDialog
        hostWindow: window
        controller: window.backend.rescueVideoController
        errorHandler: window.showAppError
        nativeTitleBarConfigurator: function () {
            window.backend.configureNativeTitleBar(rescueVideoDialog)
        }
    }

    DutySheetToolPanel {
        id: dutySheetDialog
        objectName: "dutySheetDialog"
        hostWindow: window
        controller: window.backend.dutySheetController
        errorHandler: window.showAppError
        onBrowseWorkbookRequested: dutyWorkbookDialog.open()
    }
    RestTimeToolPanel {
        id: restTimeDialog
        objectName: "restTimeDialog"
        hostWindow: window
        controller: window.backend.restMonthlyController
        onBrowseWorkbookRequested: restWorkbookDialog.open()
    }
    MonthlyBaseToolPanel {
        id: monthlyBaseDialog
        objectName: "monthlyBaseDialog"
        hostWindow: window
        controller: window.backend.restMonthlyController
        sessionController: window.backend.sessionController
    }
    DailyVehicleToolPanel {
        id: dailyVehicleDialog
        objectName: "dailyVehicleDialog"
        hostWindow: window
        controller: window.backend.dailyVehicleController
    }

    Item {
        id: modeTabs
        objectName: "modeTabs"
        property int currentIndex: 0
        visible: false
        onCurrentIndexChanged: {
            if (currentIndex === 1 && !window.backend.sessionController.isLoggedIn) {
                currentIndex = 0
                return
            }
            window.backend.setDutyModeActive(currentIndex === 0)
            if (currentIndex === 0)
                window.backend.returnToDutySchedule()
            else
                window.backend.openAuditMode()
            window.syncLegacyWindowGeometry()
        }
    }

    Rectangle {
        id: appTitleBar
        objectName: "appTitleBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Design.appTitleBarHeight
        color: Design.transparent
        radius: Design.noRadius
        border.width: Design.noBorderWidth
        z: 2

        RowLayout {
            id: titleMenuGroup
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height
            spacing: 4
            z: 1

            Label {
                objectName: "appTitleLabel"
                Layout.preferredWidth: 98
                text: "SinpoSmart"
                color: Design.infoText
                font.pixelSize: Design.controlSize
                font.bold: true
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }

            DutyOperationBar {
                id: dutyOperationBar
                backend: window.backend
                hostWindow: window
                modeIndex: modeTabs.currentIndex
                onModeChangeRequested: function(index) {
                    modeTabs.currentIndex = index
                }
            }
        }

        Item {
            id: titleWindowControls
            objectName: "titleWindowControls"
            anchors.right: parent.right
            anchors.rightMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            width: Design.appWindowControlWidth * (window.canResizeWindow ? 3 : 2)
            height: parent.height
            z: 1

            AppleButton {
                objectName: "titleMinimizeButton"
                x: 0
                width: Design.appWindowControlWidth
                height: parent.height
                implicitWidth: Design.appWindowControlWidth
                implicitHeight: Design.appTitleBarHeight
                leftPadding: 0
                rightPadding: 0
                text: ""
                iconKind: "minimize"
                tone: "windowControl"
                font.pixelSize: Design.appWindowControlIconSize
                font.weight: Font.Normal
                instantFeedback: true
                showFocusRing: false
                focusPolicy: Qt.NoFocus
                scale: 1
                Accessible.name: "縮小視窗"
                onClicked: window.showMinimized()
            }

            Loader {
                id: titleMaximizeButtonLoader
                objectName: "titleMaximizeButtonLoader"
                active: window.canResizeWindow
                x: Design.appWindowControlWidth
                width: active ? Design.appWindowControlWidth : 0
                height: parent.height

                sourceComponent: AppleButton {
                    objectName: "titleMaximizeButton"
                    anchors.fill: parent
                    leftPadding: 0
                    rightPadding: 0
                    text: ""
                    iconKind: "maximize"
                    iconToggled: window.visibility === Window.Maximized
                    tone: "windowControl"
                    instantFeedback: true
                    showFocusRing: false
                    focusPolicy: Qt.NoFocus
                    scale: 1
                    Accessible.name: window.visibility === Window.Maximized ? "還原視窗" : "最大化視窗"
                    onClicked: window.toggleWindowMaximize()

                }
            }

            AppleButton {
                objectName: "titleCloseButton"
                x: parent.width - Design.appWindowControlWidth
                width: Design.appWindowControlWidth
                height: parent.height
                implicitWidth: Design.appWindowControlWidth
                implicitHeight: Design.appTitleBarHeight
                leftPadding: 0
                rightPadding: 0
                text: ""
                iconKind: "close"
                tone: "windowClose"
                font.pixelSize: Design.appWindowControlIconSize
                font.weight: Font.Normal
                instantFeedback: true
                showFocusRing: false
                focusPolicy: Qt.NoFocus
                scale: 1
                Accessible.name: "關閉視窗"
                onClicked: window.close()
            }
        }

        Item {
            id: titleDragRegion
            objectName: "titleDragRegion"
            anchors.left: titleMenuGroup.right
            anchors.right: titleWindowControls.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            z: 0

            TapHandler {
                acceptedButtons: Qt.LeftButton
                onTapped: dutyOperationBar.closeOpenMenus()
            }

            DragHandler {
                target: null
                enabled: !dutyOperationBar.hasOpenMenu && window.visibility !== Window.Maximized
                onActiveChanged: {
                    if (active)
                        window.startSystemMove()
                }
            }
        }
    }

    MouseArea {
        anchors.left: parent.left
        anchors.top: appTitleBar.bottom
        anchors.bottom: parent.bottom
        width: Design.appResizeHandleWidth
        enabled: window.canResizeWindow && window.visibility !== Window.Maximized
        cursorShape: Qt.SizeHorCursor
        z: 3
        onPressed: window.startSystemResize(Qt.LeftEdge)
    }
    MouseArea {
        anchors.right: parent.right
        anchors.top: appTitleBar.bottom
        anchors.bottom: parent.bottom
        width: Design.appResizeHandleWidth
        enabled: window.canResizeWindow && window.visibility !== Window.Maximized
        cursorShape: Qt.SizeHorCursor
        z: 3
        onPressed: window.startSystemResize(Qt.RightEdge)
    }
    MouseArea {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Design.appResizeHandleWidth
        enabled: window.canResizeWindow && window.visibility !== Window.Maximized
        cursorShape: Qt.SizeVerCursor
        z: 3
        onPressed: window.startSystemResize(Qt.BottomEdge)
    }

    ColumnLayout {
        objectName: "mainContentHost"
        x: 14
        y: Design.appTitleBarHeight + Design.appContentTopSpacing
        width: modeTabs.currentIndex === 1 ? window.auditMainWidth - 28 : window.dutyMainWidth - 28
        height: window.height - Design.appTitleBarHeight
                - Design.appContentTopSpacing - Design.appContentBottomSpacing
        spacing: 10

        SessionHeader {
            id: sessionHeader
            backend: window.backend
            visible: modeTabs.currentIndex === 0
            onAccountManagerRequested: accountManagerWindow.open()
            onWorkLogSettingsRequested: {
                window.backend.workLogSettingsController.load()
                workLogSettingsDialog.open()
            }
        }

        AuditFilterPanel {
            id: auditFilterPanel
            hostWindow: window
            backend: window.backend
            auditModeActive: modeTabs.currentIndex === 1
        }

        DutyQuickToolsPanel {
            id: dutyQuickToolsPanel
            backend: window.backend
            hostWindow: window
            dutyModeActive: modeTabs.currentIndex === 0
            dutySheetPanel: dutySheetDialog
            dailyVehiclePanel: dailyVehicleDialog
            rescueVideoWindow: rescueVideoDialog
            restTimePanel: restTimeDialog
            monthlyBasePanel: monthlyBaseDialog
        }

        DutyTaskArea {
            id: dutyTaskArea
            backend: window.backend
            hostWindow: window
            modeIndex: modeTabs.currentIndex
            onAuditDetailRequested: function(fullDetailText) {
                window.auditDetailText = fullDetailText
                auditDetailDialog.open()
            }
        }

        WorkLogSettingsPanel {
            id: workLogSettingsDialog
            hostWindow: window
            controller: window.backend.workLogSettingsController
        }
        Item {
            visible: modeTabs.currentIndex === 0 && !window.backend.sessionController.isLoggedIn
            Layout.fillHeight: visible
        }
    }

    Component.onCompleted: {
        Qt.callLater(function() {
            window.backend.sessionController.restoreSavedAccountSelection()
        })
        window.syncLegacyWindowGeometry()
        window.positionInAvailableWorkArea()
        window.lastHandledLoginState = window.backend.sessionController.isLoggedIn
    }
}
