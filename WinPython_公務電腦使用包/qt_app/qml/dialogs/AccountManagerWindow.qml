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
    readonly property int accountCardWidth: 280
    readonly property int dialogWidth: 44 + columnCount * accountCardWidth + Math.max(0, columnCount - 1) * 8
    readonly property int contentHeight: 162 + listHeight
    readonly property int dialogHeight: Design.appTitleBarHeight + contentHeight
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
    readonly property int listHeight: Math.max(60, maximumRows * 48 + 4)

    function open() {
        show()
        raise()
        requestActivate()
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

            GridLayout {
                id: accountGrid
                objectName: "savedAccountGrid"
                anchors.fill: parent
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
                                onClicked: {
                                    accountManagerWindow.pendingAccountIdentity = savedAccountRow.identity
                                    accountManagerWindow.pendingAccountLabel = savedAccountRow.label
                                    accountDeleteConfirmation.open()
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
        id: accountDeleteConfirmation
        objectName: "accountDeleteConfirmation"
        anchors.centerIn: parent
        modal: true
        title: "確認刪除"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "刪除帳號"
        acceptTone: "dangerFilled"
        onAccepted: {
            accountManagerWindow.sessionController.deleteSavedAccount(
                accountManagerWindow.pendingAccountIdentity
            )
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
