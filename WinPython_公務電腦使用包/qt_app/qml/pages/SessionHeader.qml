import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ColumnLayout {
    id: sessionHeader
    required property var backend
    property var hostWindow: null
    property alias userIdText: userIdField.text
    property alias passwordText: passwordField.text
    signal accountManagerRequested
    signal workLogSettingsRequested
    Layout.fillWidth: true
    spacing: 10

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 54
        radius: Design.radius
        color: Design.strongText
        border.color: Design.comboBorder

        Label {
            anchors.fill: parent
            text: sessionHeader.backend.dutyController.currentDateText + " " + sessionHeader.backend.dutyController.currentTimeText
            color: Design.panel
            font.pixelSize: Design.panelTitleSize
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        Layout.fillWidth: true
        visible: sessionHeader.backend.sessionController.isLoggedIn
        Layout.preferredHeight: visible ? 86 : 0
        Layout.minimumHeight: Layout.preferredHeight
        Layout.maximumHeight: Layout.preferredHeight
        radius: Design.radius
        color: Design.panel
        border.color: Design.border

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: 8
            anchors.bottomMargin: 6
            spacing: 6

            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: "消防勤務管理系統"
                    color: Design.infoText
                    font.pixelSize: Design.windowTitleSize
                    font.bold: true
                }
                SettingsButton {
                    objectName: "settingsTab"
                    visible: !sessionHeader.backend.readOnlyAcceptance
                    Accessible.name: "工作紀錄預設內容"
                    onClicked: sessionHeader.workLogSettingsRequested()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Label {
                    id: loggedInStatusLabel
                    objectName: "loggedInStatusLabel"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 24
                    visible: !loggedInErrorStatusBar.visible
                    text: sessionHeader.backend.sessionController.loginStatus
                    color: sessionHeader.backend.sessionController.loginStatusTone === "error" ? Design.dangerStrong : sessionHeader.backend.sessionController.loginStatusTone === "warning" ? Design.warningStrong : sessionHeader.backend.sessionController.loginStatusTone === "info" ? Design.infoText : sessionHeader.backend.sessionController.loginStatusTone === "neutral" ? Design.muted : Design.successText
                    font.pixelSize: Design.controlSize
                    font.bold: true
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                    verticalAlignment: Text.AlignVCenter
                    activeFocusOnTab: truncated
                    Accessible.name: text

                    HoverHandler {
                        id: loggedInStatusHover
                    }

                    ToolTip.visible: loggedInStatusLabel.truncated
                                         && (loggedInStatusHover.hovered || loggedInStatusLabel.activeFocus)
                    ToolTip.text: loggedInStatusLabel.text
                    ToolTip.delay: 400
                    ToolTip.timeout: 10000
                }
                ToolStatusBar {
                    id: loggedInErrorStatusBar
                    objectName: "loggedInErrorStatusBar"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    compact: true
                    onlyShowErrors: true
                    text: sessionHeader.backend.sessionController.loginStatus
                    onDetailsRequested: function(message) {
                        sessionHeader.hostWindow.showErrorDetails("登入錯誤", message)
                    }
                }
                DangerButton {
                    implicitHeight: 30
                    implicitWidth: 74
                    text: "登出"
                    onClicked: sessionHeader.backend.requestLogout()
                }
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        visible: !sessionHeader.backend.sessionController.isLoggedIn
        Layout.preferredHeight: visible ? 224 : 0
        Layout.minimumHeight: Layout.preferredHeight
        Layout.maximumHeight: Layout.preferredHeight
        radius: Design.radius
        color: Design.panel
        border.color: Design.border

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: 8
            anchors.bottomMargin: 6
            spacing: 6

            Label {
                text: "消防勤務管理系統"
                color: Design.infoText
                font.pixelSize: Design.windowTitleSize
                font.bold: true
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.preferredWidth: 34
                    text: "帳號"
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                }
                AppleTextField {
                    id: userIdField
                    objectName: "loginUserIdField"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 38
                    enabled: !sessionHeader.backend.sessionController.isBusy
                }

                AppleButton {
                    objectName: "savedAccountManagerButton"
                    Layout.preferredWidth: 136
                    implicitHeight: 38
                    enabled: !sessionHeader.backend.sessionController.isBusy
                    text: "帳號選擇"
                    tone: "infoStrong"
                    onClicked: sessionHeader.accountManagerRequested()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.preferredWidth: 34
                    text: "密碼"
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                }

                AppleTextField {
                    id: passwordField
                    objectName: "loginPasswordField"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    enabled: !sessionHeader.backend.sessionController.isBusy
                    echoMode: TextInput.Password
                    passwordCharacter: "*"
                    onAccepted: loginButton.clicked()
                }

                AppleCheckBox {
                    id: rememberLoginCheck
                    Layout.preferredWidth: 136
                    enabled: !sessionHeader.backend.sessionController.isBusy && !sessionHeader.backend.readOnlyAcceptance
                    text: sessionHeader.backend.readOnlyAcceptance ? "只讀驗收不保存帳密" : "記住帳號密碼"
                    font.pixelSize: Design.captionSize
                }
            }

            PrimaryButton {
                id: loginButton
                objectName: "loginSubmitButton"
                Layout.fillWidth: true
                implicitHeight: 38
                enabled: !sessionHeader.backend.sessionController.isBusy
                text: sessionHeader.backend.sessionController.isBusy ? "登入中…" : "登入"
                onClicked: sessionHeader.backend.sessionController.login(userIdField.text, passwordField.text, rememberLoginCheck.checked)
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 24
                spacing: 8

                Label {
                    id: loginStatusLabel
                    objectName: "loginStatusLabel"
                    Layout.fillWidth: true
                    visible: !loginErrorStatusBar.visible
                    text: sessionHeader.backend.sessionController.loginStatus
                    color: sessionHeader.backend.sessionController.loginStatusTone === "error" ? Design.dangerStrong : sessionHeader.backend.sessionController.loginStatusTone === "warning" ? Design.warningStrong : sessionHeader.backend.sessionController.loginStatusTone === "info" ? Design.infoText : sessionHeader.backend.sessionController.loginStatusTone === "neutral" ? Design.muted : Design.successText
                    font.pixelSize: Design.controlSize
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    activeFocusOnTab: truncated
                    Accessible.name: text

                    HoverHandler {
                        id: loginStatusHover
                    }

                    ToolTip.visible: loginStatusLabel.truncated
                                         && (loginStatusHover.hovered || loginStatusLabel.activeFocus)
                    ToolTip.text: loginStatusLabel.text
                    ToolTip.delay: 400
                    ToolTip.timeout: 10000
                }
                ToolStatusBar {
                    id: loginErrorStatusBar
                    objectName: "loginErrorStatusBar"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    compact: true
                    onlyShowErrors: true
                    text: sessionHeader.backend.sessionController.loginStatus
                    onDetailsRequested: function(message) {
                        sessionHeader.hostWindow.showErrorDetails("登入錯誤", message)
                    }
                }
            }
        }
    }
}
