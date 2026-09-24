import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

AppleDialog {
    id: root
    objectName: "updateHistoryDialog"
    required property var updateController
    property bool updateNoticeMode: false

    anchors.centerIn: parent
    width: Math.max(350, Math.min(640, parent ? parent.width - 40 : 640))
    height: Math.max(260, Math.min(560, parent ? parent.height - 32 : 560))
    modal: true
    closePolicy: Popup.NoAutoClose
    standardButtons: Dialog.Close
    title: updateNoticeMode ? "更新完成" : "更新日誌"
    closeText: updateNoticeMode ? "我已閱讀，進入系統" : "關閉"

    function openHistory() {
        updateNoticeMode = false
        open()
    }

    function openPendingUpdateNotice() {
        if (visible)
            return updateNoticeMode
        if (!updateController.showPendingUpdateNotice())
            return false
        updateNoticeMode = true
        open()
        return true
    }

    onClosed: {
        if (updateNoticeMode)
            updateController.dismissPendingUpdateNotice()
        updateNoticeMode = false
    }

    contentItem: ColumnLayout {
        spacing: 8

        Label {
            Layout.fillWidth: true
            visible: root.updateNoticeMode
            text: "系統已完成更新。請閱讀本次更新摘要，關閉此視窗後即可進入系統。"
            color: Design.infoText
            font.pixelSize: Design.bodySize
            wrapMode: Text.WordWrap
        }

        Label {
            Layout.fillWidth: true
            visible: !root.updateNoticeMode
            text: "依主要功能整理，不列出每一項細部修正。"
            color: Design.muted
            font.pixelSize: Design.bodySize
            wrapMode: Text.WordWrap
        }

        ScrollView {
            id: historyScroll
            objectName: "updateHistoryScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: historyScroll.availableWidth
                spacing: 10

                Repeater {
                    id: historyEntries
                    model: root.updateNoticeMode
                           ? root.updateController.pendingUpdateNotice.releases
                           : root.updateController.updateHistory.entries

                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: entryContent.implicitHeight + 24
                        radius: Design.radiusMedium
                        color: Design.panel
                        border.width: Design.borderWidth
                        border.color: Design.border

                        ColumnLayout {
                            id: entryContent
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 6

                            Label {
                                Layout.fillWidth: true
                                text: modelData.version
                                      ? modelData.period + "　版本 " + modelData.version
                                      : modelData.period
                                color: Design.muted
                                font.pixelSize: Design.bodySize
                                wrapMode: Text.WordWrap
                            }

                            Label {
                                Layout.fillWidth: true
                                text: modelData.title
                                color: Design.infoText
                                font.pixelSize: Design.sectionTitleSize
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                text: modelData.items.map(function(item) {
                                    return "• " + item
                                }).join("\n")
                                color: Design.text
                                font.pixelSize: Design.bodySize
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: historyEntries.count === 0
                    text: "目前沒有可顯示的更新紀錄。"
                    color: Design.muted
                    font.pixelSize: Design.bodySize
                }
            }
        }
    }
}
