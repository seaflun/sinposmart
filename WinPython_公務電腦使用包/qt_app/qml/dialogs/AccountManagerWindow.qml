pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

Window {
    id: accountManagerWindow
    required property var hostWindow
    required property var sessionController
    property string pendingAccountIdentity: ""
    property string pendingAccountLabel: ""
    objectName: "accountManagerWindow"
    visible: false
    readonly property int windowMargin: 16
    readonly property int preferredAccountCardWidth: 280
    readonly property int naturalDialogWidth: 44 + columnCount * preferredAccountCardWidth + Math.max(0, columnCount - 1) * 8
    readonly property int naturalDialogHeight: Design.appTitleBarHeight + 162 + naturalListHeight
    readonly property int workAreaWidth: screen ? screen.desktopAvailableWidth : naturalDialogWidth + 2 * windowMargin
    readonly property int workAreaHeight: screen ? screen.desktopAvailableHeight : naturalDialogHeight + 2 * windowMargin
    readonly property int dialogWidth: Math.min(naturalDialogWidth, Math.max(1, workAreaWidth - 2 * windowMargin))
    readonly property int accountCardWidth: Math.floor((dialogWidth - 44 - Math.max(0, columnCount - 1) * 8) / columnCount)
    readonly property int contentHeight: 162 + listHeight
    readonly property int dialogHeight: Math.min(workAreaHeight - 2 * windowMargin,
                                                Math.max(Design.appTitleBarHeight + contentHeight,
                                                         noticeSettingsDialog.visible ? noticeSettingsDialog.implicitHeight + 2 * windowMargin : 0))
    width: dialogWidth
    height: dialogHeight
    minimumWidth: dialogWidth
    maximumWidth: dialogWidth
    minimumHeight: dialogHeight
    maximumHeight: dialogHeight
    title: "SinpoSmart - 帳號管理"
    color: Design.transparent
    flags: Qt.Dialog | Qt.FramelessWindowHint
    modality: Qt.WindowModal
    transientParent: hostWindow

    readonly property int accountCount: accountRepeater.count
    readonly property int columnCount: Math.max(2, Math.ceil(accountCount / 15))
    readonly property int maximumRows: Math.min(15, accountCount)
    readonly property int naturalListHeight: Math.max(60, maximumRows * 48 + 4)
    readonly property int maximumListHeight: Math.max(
            60,
            workAreaHeight - 2 * windowMargin - Design.appTitleBarHeight - 162
        )
    readonly property int listHeight: Math.min(naturalListHeight, maximumListHeight)

    function positionInAvailableWorkArea() {
        if (!screen)
            return
        const availableX = screen.virtualX
        const availableY = screen.virtualY
        const availableWidth = screen.desktopAvailableWidth
        const availableHeight = screen.desktopAvailableHeight
        const maximumX = availableX + Math.max(windowMargin, availableWidth - width - windowMargin)
        const maximumY = availableY + Math.max(windowMargin, availableHeight - height - windowMargin)
        x = Math.max(availableX + windowMargin, Math.min(
                    availableX + Math.round((availableWidth - width) / 2), maximumX))
        y = Math.max(availableY + windowMargin, Math.min(
                    availableY + Math.round((availableHeight - height) / 2), maximumY))
    }

    function open() {
        if (hostWindow.backend.readOnlyAcceptance)
            return
        show()
        Qt.callLater(accountManagerWindow.positionInAvailableWorkArea)
        raise()
        requestActivate()
    }

    onVisibleChanged: {
        if (visible)
            Qt.callLater(accountManagerWindow.positionInAvailableWorkArea)
        else {
            noticePasswordField.text = ""
            noticeSettingsDialog.close()
        }
    }

    onWidthChanged: {
        if (visible)
            Qt.callLater(accountManagerWindow.positionInAvailableWorkArea)
    }

    onHeightChanged: {
        if (visible)
            Qt.callLater(accountManagerWindow.positionInAvailableWorkArea)
    }

    Rectangle {
        anchors.fill: parent
        radius: Design.radiusPanel
        color: Design.background
        border.width: Design.noBorderWidth
    }

    Rectangle {
        id: accountTitleBar
        objectName: "accountTitleBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Design.appTitleBarHeight
        color: Design.transparent
        z: 2

        DragHandler {
            target: null
            enabled: accountManagerWindow.visibility !== Window.Maximized
            onActiveChanged: {
                if (active)
                    accountManagerWindow.startSystemMove()
            }
        }

        Label {
            id: accountTitleLabel
            objectName: "accountTitleLabel"
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: "SinpoSmart - 帳號管理"
            color: Design.infoText
            font.pixelSize: Design.controlSize
            font.bold: true
        }

        AppleButton {
            objectName: "accountTitleCloseButton"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
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
            Accessible.name: "關閉帳號管理"
            onClicked: accountManagerWindow.close()
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: accountTitleBar.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 12
        anchors.bottomMargin: 12
        color: Design.transparent

        Rectangle {
            id: accountManagerHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 68
            radius: Design.radius
            color: Design.comboHover
            border.color: Design.comboBorder

            Column {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                anchors.topMargin: 9
                spacing: 2

                Label {
                    text: "帳號選擇"
                    color: Design.infoText
                    font.pixelSize: Design.subtitleSize
                    font.bold: true
                }
                Label {
                    text: "選擇已儲存帳號，或刪除不再使用的項目。"
                    color: Design.muted
                    font.pixelSize: Design.bodySize
                }
            }
        }

        Item {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: accountManagerHeader.bottom
            anchors.topMargin: 10
            height: accountManagerWindow.listHeight

            Flickable {
                id: accountListViewport
                objectName: "savedAccountViewport"
                anchors.fill: parent
                contentWidth: width
                contentHeight: accountGrid.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                ScrollBar.vertical: ScrollBar { }

                GridLayout {
                    id: accountGrid
                    objectName: "savedAccountGrid"
                    width: accountListViewport.width
                    columns: accountManagerWindow.columnCount
                    rows: Math.max(1, accountManagerWindow.maximumRows)
                    columnSpacing: 8
                    rowSpacing: 6

                    Repeater {
                        id: accountRepeater
                        model: accountManagerWindow.sessionController.savedAccountsModel

                        delegate: Rectangle {
                            id: savedAccountRow
                            required property int index
                            required property string identity
                            required property string label
                            Layout.row: index % 15
                            Layout.column: Math.floor(index / 15)
                            Layout.preferredWidth: accountManagerWindow.accountCardWidth
                            Layout.preferredHeight: 42
                            radius: Design.radius
                            color: Design.panel
                            border.color: Design.border

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8

                                AppleButton {
                                    objectName: "savedAccountDeleteButton"
                                    implicitWidth: 28
                                    implicitHeight: 28
                                    leftPadding: 0
                                    rightPadding: 0
                                    text: "X"
                                    tone: "danger"
                                    enabled: !accountManagerWindow.hostWindow.backend.readOnlyAcceptance
                                    onClicked: {
                                        if (!accountManagerWindow.hostWindow.backend.readOnlyAcceptance) {
                                            accountManagerWindow.pendingAccountIdentity = savedAccountRow.identity
                                            accountManagerWindow.pendingAccountLabel = savedAccountRow.label
                                            accountDeleteConfirmation.open()
                                        }
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: savedAccountRow.label
                                    color: Design.text
                                    font.pixelSize: Design.bodySize
                                    elide: Text.ElideRight
                                }
                                AppleButton {
                                    objectName: "savedAccountSelectButton"
                                    implicitWidth: 56
                                    implicitHeight: 28
                                    leftPadding: 8
                                    rightPadding: 8
                                    text: "選擇"
                                    tone: "infoStrong"
                                    onClicked: {
                                        accountManagerWindow.sessionController.selectSavedAccount(
                                            savedAccountRow.identity
                                        )
                                        accountManagerWindow.close()
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                anchors.fill: parent
                visible: accountManagerWindow.accountCount === 0
                radius: Design.radius
                color: Design.panel
                border.color: Design.border

                Label {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 12
                    text: "目前沒有已儲存帳號。"
                    color: Design.muted
                    font.pixelSize: Design.labelSize
                }
            }
        }

        AppleButton {
            objectName: "noticeSettingsButton"
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            implicitHeight: 34
            text: "通報帳號設定"
            tone: "neutralStrong"
            enabled: !accountManagerWindow.hostWindow.backend.readOnlyAcceptance
            onClicked: noticeSettingsDialog.open()
        }

        AppleButton {
            objectName: "savedAccountCloseButton"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            implicitWidth: 88
            implicitHeight: 34
            text: "關閉"
            tone: "neutralStrong"
            onClicked: accountManagerWindow.close()
        }
    }

    AppleDialog {
        id: noticeSettingsDialog
        objectName: "noticeSettingsDialog"
        anchors.centerIn: parent
        modal: true
        title: "通報帳號設定"
        standardButtons: Dialog.Close
        width: Math.min(500, accountManagerWindow.width - 32)
        padding: 20
        property bool editingPassword: false
        property bool saveAttempted: false
        property var keyboardState: ({available: false})
        readonly property string settingsState: accountManagerWindow.sessionController.noticeSettingsState
        readonly property bool passwordConfigured: accountManagerWindow.sessionController.noticePasswordConfigured
        readonly property bool verifying: settingsState === "waiting" || settingsState === "verifying"
        readonly property bool errorVisible: settingsState === "error" && (!editingPassword || saveAttempted)
        readonly property bool verified: settingsState === "verified" && !editingPassword
        readonly property string resultTitle: errorVisible ? (accountManagerWindow.sessionController.noticeSettingsErrorKind === "storage" ? "密碼尚未儲存" : "登入驗證未完成")
                                             : editingPassword ? (passwordConfigured ? "變更通報密碼" : "設定通報密碼")
                                             : settingsState === "waiting" ? "等待驗證登入"
                                             : settingsState === "verifying" ? "正在驗證登入"
                                             : verified ? "登入驗證成功" : "已儲存通報密碼"
        readonly property string resultDescription: errorVisible || verifying
                                                   ? accountManagerWindow.sessionController.noticeSettingsStatus
                                                   : editingPassword ? "輸入新密碼後儲存，會自動驗證登入。取消可保留原設定。"
                                                   : verified ? "密碼已加密儲存，公務信箱登入正常。"
                                                   : "密碼已加密儲存在此電腦。可測試登入，或變更密碼。"
        onOpened: {
            noticePasswordField.text = ""
            accountManagerWindow.sessionController.refreshNoticeSettings()
            saveAttempted = false
            editingPassword = !passwordConfigured
        }
        onClosed: {
            noticePasswordField.text = ""
            editingPassword = false
        }
        onVisibleChanged: {
            if (!visible)
                noticePasswordField.text = ""
        }

        header: Item {
            implicitHeight: 62
            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 20
                spacing: 4
                Label {
                    text: noticeSettingsDialog.title
                    color: Design.text
                    font.pixelSize: Design.panelTitleSize
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "新坡分隊公務信箱"
                    color: Design.secondaryText
                    font.pixelSize: Design.bodySize
                }
            }
        }

        Timer {
            interval: 150
            repeat: true
            triggeredOnStart: true
            running: noticeSettingsDialog.visible && noticeSettingsDialog.editingPassword && accountManagerWindow.active
            onTriggered: noticeSettingsDialog.keyboardState = accountManagerWindow.sessionController.passwordKeyboardState()
        }

        ColumnLayout {
            width: parent.width
            spacing: 18
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Label {
                    text: "登入帳號"
                    color: Design.secondaryText
                    font.pixelSize: Design.labelSize
                }
                Label {
                    Layout.fillWidth: true
                    text: "tyfd01214"
                    color: Design.text
                    font.pixelSize: Design.sectionTitleSize
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "固定帳號"
                    color: Design.secondaryText
                    font.pixelSize: Design.captionSize
                }
            }

            Rectangle {
                objectName: "noticeSettingsResult"
                Layout.fillWidth: true
                implicitHeight: noticeResultRow.implicitHeight + 32
                radius: Design.radiusLarge
                color: noticeSettingsDialog.errorVisible ? Design.dangerSurface
                       : noticeSettingsDialog.verified ? Design.successDoneSurface : Design.subtleSurface
                border.width: Design.borderWidth
                border.color: noticeSettingsDialog.errorVisible ? Design.dangerBorder
                              : noticeSettingsDialog.verified ? Design.successBorder : Design.border
                Accessible.role: Accessible.AlertMessage
                Accessible.name: noticeSettingsDialog.resultTitle + "。" + noticeSettingsDialog.resultDescription

                RowLayout {
                    id: noticeResultRow
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 14
                    Rectangle {
                        Layout.alignment: Qt.AlignTop
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        radius: width / 2
                        color: noticeSettingsDialog.errorVisible ? Design.dangerFill
                               : noticeSettingsDialog.verified ? Design.successAction : Design.comboButton
                        Accessible.ignored: true
                        Label {
                            anchors.centerIn: parent
                            visible: !noticeSettingsDialog.verifying && (noticeSettingsDialog.errorVisible || noticeSettingsDialog.editingPassword)
                            text: noticeSettingsDialog.errorVisible ? "!" : "+"
                            color: noticeSettingsDialog.errorVisible || noticeSettingsDialog.verified ? Design.panel : Design.blue
                            font.pixelSize: Design.heroTitleSize
                            font.weight: Font.DemiBold
                        }
                        Canvas {
                            anchors.centerIn: parent
                            width: 20
                            height: 16
                            visible: !noticeSettingsDialog.verifying && !noticeSettingsDialog.errorVisible && !noticeSettingsDialog.editingPassword
                            property color markColor: noticeSettingsDialog.verified ? Design.panel : Design.blue
                            onMarkColorChanged: requestPaint()
                            onVisibleChanged: requestPaint()
                            onPaint: {
                                const context = getContext("2d")
                                context.reset()
                                context.strokeStyle = markColor
                                context.lineWidth = 2.5
                                context.lineCap = "round"
                                context.lineJoin = "round"
                                context.beginPath()
                                context.moveTo(2, 8)
                                context.lineTo(7, 13)
                                context.lineTo(18, 2)
                                context.stroke()
                            }
                        }
                        BusyIndicator {
                            anchors.centerIn: parent
                            width: 30
                            height: 30
                            running: noticeSettingsDialog.verifying
                            visible: running
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Label {
                            objectName: "noticeSettingsStatusTitle"
                            Layout.fillWidth: true
                            text: noticeSettingsDialog.resultTitle
                            color: noticeSettingsDialog.errorVisible ? Design.dangerStrong
                                   : noticeSettingsDialog.verified ? Design.successText : Design.text
                            wrapMode: Text.WordWrap
                            font.pixelSize: Design.sectionTitleSize
                            font.weight: Font.DemiBold
                        }
                        Label {
                            objectName: "noticeSettingsStatusMessage"
                            Layout.fillWidth: true
                            text: noticeSettingsDialog.resultDescription
                            color: Design.secondaryText
                            wrapMode: Text.WordWrap
                            font.pixelSize: Design.labelSize
                            lineHeight: 1.2
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                visible: noticeSettingsDialog.editingPassword
                Label {
                    text: noticeSettingsDialog.passwordConfigured ? "新通報密碼" : "通報密碼"
                    color: Design.text
                    font.pixelSize: Design.labelSize
                    font.weight: Font.DemiBold
                }
                AppleTextField {
                    id: noticePasswordField
                    objectName: "noticePasswordField"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42
                    echoMode: TextInput.Password
                    placeholderText: noticeSettingsDialog.passwordConfigured ? "輸入新密碼" : "輸入通報密碼"
                    enabled: !accountManagerWindow.hostWindow.backend.readOnlyAcceptance && !noticeSettingsDialog.verifying
                    onAccepted: {
                        if (saveNoticePasswordButton.enabled)
                            saveNoticePasswordButton.clicked()
                    }
                }
                Label {
                    objectName: "noticePasswordCaseHint"
                    Layout.fillWidth: true
                    visible: noticeSettingsDialog.keyboardState.available
                    text: "目前輸入：" + (noticeSettingsDialog.keyboardState.uppercase ? "大寫" : "小寫")
                          + (noticeSettingsDialog.keyboardState.capsLock ? " · Caps Lock 已開啟" : "")
                    color: noticeSettingsDialog.keyboardState.capsLock ? Design.warningStrong : Design.secondaryText
                    font.pixelSize: Design.captionSize
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AppleButton {
                    objectName: "noticeChangePasswordButton"
                    visible: noticeSettingsDialog.passwordConfigured && !noticeSettingsDialog.editingPassword
                    enabled: !noticeSettingsDialog.verifying && !accountManagerWindow.hostWindow.backend.readOnlyAcceptance
                    text: "變更密碼"
                    tone: "neutralStrong"
                    onClicked: {
                        noticeSettingsDialog.saveAttempted = false
                        noticeSettingsDialog.editingPassword = true
                        noticePasswordField.text = ""
                        noticePasswordField.forceActiveFocus()
                    }
                }
                AppleButton {
                    objectName: "noticeCancelPasswordButton"
                    visible: noticeSettingsDialog.editingPassword && noticeSettingsDialog.passwordConfigured
                    text: "取消變更"
                    tone: "neutralStrong"
                    onClicked: {
                        noticePasswordField.text = ""
                        noticeSettingsDialog.editingPassword = false
                    }
                }
                Item {
                    Layout.fillWidth: true
                }
                PrimaryButton {
                    objectName: "noticeVerifyLoginButton"
                    visible: noticeSettingsDialog.passwordConfigured && !noticeSettingsDialog.editingPassword
                    enabled: !noticeSettingsDialog.verifying && !accountManagerWindow.hostWindow.backend.readOnlyAcceptance
                    text: noticeSettingsDialog.verifying ? "驗證中…"
                          : noticeSettingsDialog.settingsState === "error" && accountManagerWindow.sessionController.noticeSettingsErrorKind === "verification" ? "再試一次" : "測試登入"
                    onClicked: accountManagerWindow.hostWindow.backend.noticeCollectionController.verifyLogin()
                }
                PrimaryButton {
                    id: saveNoticePasswordButton
                    objectName: "saveNoticePasswordButton"
                    visible: noticeSettingsDialog.editingPassword
                    text: "儲存並驗證登入"
                    enabled: !accountManagerWindow.hostWindow.backend.readOnlyAcceptance && !noticeSettingsDialog.verifying && noticePasswordField.text.length > 0
                    onClicked: {
                        noticeSettingsDialog.saveAttempted = true
                        if (accountManagerWindow.sessionController.saveNoticePassword(noticePasswordField.text)) {
                            noticePasswordField.text = ""
                            noticeSettingsDialog.editingPassword = false
                        }
                    }
                }
            }
        }
    }

    AppleDialog {
        id: accountDeleteConfirmation
        objectName: "accountDeleteConfirmation"
        anchors.centerIn: parent
        modal: true
        title: "確認刪除"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "刪除帳號"
        acceptTone: "dangerFilled"
        onAccepted: {
            if (!accountManagerWindow.hostWindow.backend.readOnlyAcceptance) {
                accountManagerWindow.sessionController.deleteSavedAccount(
                    accountManagerWindow.pendingAccountIdentity
                )
            }
            accountManagerWindow.pendingAccountIdentity = ""
            accountManagerWindow.pendingAccountLabel = ""
        }
        onRejected: {
            accountManagerWindow.pendingAccountIdentity = ""
            accountManagerWindow.pendingAccountLabel = ""
        }

        Label {
            text: "確定刪除 " + accountManagerWindow.pendingAccountLabel + "？"
            color: Design.text
            wrapMode: Text.Wrap
        }
    }
}
