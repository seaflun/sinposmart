pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"
import "../components"

ApplicationWindow {
    id: noticeWindow
    objectName: "noticeHandoffWindow"
    required property var controller
    property var hostWindow: null
    readonly property var view: controller.handoffReminder
    readonly property var noticeRows: view.rows || []
    readonly property int workAreaWidth: screen ? screen.desktopAvailableWidth : 1024
    readonly property int workAreaHeight: screen ? screen.desktopAvailableHeight : 768
    width: Math.min(680, workAreaWidth - 32)
    height: Math.min(660, workAreaHeight - 32,
                     Math.max(320, 276 + Math.min(7, noticeRows.length) * 46
                              + (view.warning ? 44 : 0) + (controller.sheetLinkMessage ? 28 : 0)))
    visible: Boolean(view.visible)
    title: "SinpoSmart - 當班通報提醒"
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    modality: Qt.NonModal
    color: Design.transparent
    transientParent: null

    function positionInWorkArea() {
        if (hostWindow && hostWindow.screen)
            screen = hostWindow.screen
        x = (screen ? screen.virtualX : 0) + Math.max(16, Math.round((workAreaWidth - width) / 2))
        y = (screen ? screen.virtualY : 0) + Math.max(16, Math.round((workAreaHeight - height) / 2))
    }

    onVisibleChanged: if (visible) Qt.callLater(function() {
        noticeWindow.positionInWorkArea()
        noticeWindow.raise()
        noticeWindow.requestActivate()
    })
    onClosing: controller.dismissHandoffReminder()

    Rectangle {
        anchors.fill: parent
        radius: Design.radiusSheet
        color: Design.background
        border.width: Design.borderWidth
        border.color: Design.border
    }

    Item {
        id: titleBar
        width: parent.width
        height: Design.appTitleBarHeight

        DragHandler {
            target: null
            onActiveChanged: if (active) noticeWindow.startSystemMove()
        }

        Label {
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            text: "SinpoSmart"
            color: Design.infoText
            font.pixelSize: Design.controlSize
            font.bold: true
        }

        AppleButton {
            id: closeButton
            objectName: "noticeTitleCloseButton"
            anchors.right: parent.right
            anchors.rightMargin: 2
            width: Design.appWindowControlWidth
            height: Design.appTitleBarHeight
            leftPadding: 0
            rightPadding: 0
            text: ""
            iconKind: "close"
            tone: "windowClose"
            instantFeedback: true
            onClicked: controller.dismissHandoffReminder()
        }
    }

    Rectangle {
        id: noticePanel
        x: 12
        y: Design.appTitleBarHeight + 8
        width: parent.width - 24
        height: parent.height - 104
        radius: Design.radiusMedium
        color: Design.panel
        border.width: Design.borderWidth
        border.color: Design.border

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            RowLayout {
                Layout.fillWidth: true

                Label {
                    text: "當班通報提醒"
                    color: Design.infoText
                    font.pixelSize: Design.panelTitleSize
                    font.bold: true
                }

                Item { Layout.fillWidth: true }

                Label {
                    text: "交班前 2 分鐘・置頂提醒"
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 16

                Label {
                    id: noticeShift
                    objectName: "noticeShiftLabel"
                    text: noticeWindow.view.shiftText || ""
                    color: Design.secondaryText
                    font.pixelSize: Design.bodySize
                }

                Label {
                    objectName: "noticeLastChecked"
                    text: noticeWindow.view.lastCheckedText || ""
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                }

                Item { Layout.fillWidth: true }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 36
                radius: Design.radiusSmall
                color: Design.comboHover
                border.width: Design.borderWidth
                border.color: Design.comboBorder

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12

                    Label {
                        objectName: "noticeCountLabel"
                        text: "本班已收取 " + noticeWindow.noticeRows.length + " 則通報"
                        color: Design.infoText
                        font.pixelSize: Design.sectionTitleSize
                        font.bold: true
                    }

                    Item { Layout.fillWidth: true }

                    Label {
                        text: noticeWindow.view.handoffText || ""
                        color: Design.secondaryText
                        font.pixelSize: Design.bodySize
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                visible: Boolean(noticeWindow.view.warning)
                text: noticeWindow.view.warning || ""
                color: Design.warningText
                font.pixelSize: Design.captionSize
                wrapMode: Text.Wrap
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Design.radiusSmall
                color: Design.panel
                border.width: Design.borderWidth
                border.color: Design.taskBorder

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 1
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 28
                        color: Design.softAction

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 8
                            Label { Layout.preferredWidth: 80; text: "收取時間"; color: Design.secondaryText; font.pixelSize: Design.captionSize }
                            Label { Layout.preferredWidth: 140; text: "發布人"; color: Design.secondaryText; font.pixelSize: Design.captionSize }
                            Label { objectName: "noticeSubjectHeader"; Layout.fillWidth: true; text: "主旨"; color: Design.secondaryText; font.pixelSize: Design.captionSize }
                        }
                    }

                    ListView {
                        id: noticeList
                        objectName: "noticeHandoffList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: noticeWindow.noticeRows
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Item {
                            required property var modelData
                            width: noticeList.width
                            height: Math.max(46, publisherContent.implicitHeight + 12, noticeSubject.implicitHeight + 16)

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8
                                Label { Layout.preferredWidth: 80; text: modelData.time; color: Design.text; font.pixelSize: Design.bodySize }
                                ColumnLayout {
                                    id: publisherContent
                                    Layout.preferredWidth: 140
                                    Layout.minimumWidth: 140
                                    Layout.maximumWidth: 140
                                    Layout.fillWidth: false
                                    spacing: 1

                                    Label {
                                        objectName: "noticePublisherUnit"
                                        Layout.fillWidth: true
                                        text: modelData.unit
                                        color: Design.secondaryText
                                        font.pixelSize: Design.captionSize
                                        wrapMode: Text.Wrap
                                    }

                                    Label {
                                        objectName: "noticePublisherName"
                                        Layout.fillWidth: true
                                        text: modelData.name
                                        color: Design.text
                                        font.pixelSize: Design.bodySize
                                    }
                                }
                                Label { id: noticeSubject; objectName: "noticeSubject"; Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.subject; color: Design.text; font.pixelSize: Design.bodySize; horizontalAlignment: Text.AlignLeft; wrapMode: Text.Wrap }
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: Design.borderWidth
                                color: Design.taskBorder
                            }
                        }
                    }
                }
            }
        }
    }

    Label {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: footerButtons.top
        anchors.leftMargin: 26
        anchors.rightMargin: 26
        anchors.bottomMargin: 6
        visible: controller.sheetLinkMessage.length > 0
        text: controller.sheetLinkMessage
        color: Design.warningText
        font.pixelSize: Design.captionSize
        wrapMode: Text.Wrap
    }

    Row {
        id: footerButtons
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        spacing: 8

        AppleButton {
            objectName: "noticeSheetButton"
            text: controller.sheetLinkBusy ? "取得連結中…" : "開啟通報試算表"
            enabled: !controller.sheetLinkBusy
            tone: "neutralStrong"
            implicitWidth: 142
            implicitHeight: 34
            onClicked: controller.openNoticeSheet()
        }

        AppleButton {
            objectName: "noticeDismissButton"
            text: "我知道了"
            tone: "primary"
            implicitWidth: 92
            implicitHeight: 34
            onClicked: controller.dismissHandoffReminder()
        }
    }
}
