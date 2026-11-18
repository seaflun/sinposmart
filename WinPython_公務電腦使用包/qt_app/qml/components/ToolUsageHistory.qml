pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

ToolFormCard {
    id: toolUsageHistory
    required property var backend
    required property string toolId
    property bool currentOperatorOnly: false
    property var usageModel: null
    property var vehicleAssignments: ({date: "", rows: []})
    objectName: toolId + "UsageHistory"
    Layout.fillWidth: true

    function refresh() {
        usageModel = backend.toolController.usageModel(toolId, backend.sessionController.actorNo, backend.sessionController.userId, backend.sessionController.displayName, currentOperatorOnly);
        if (toolId === "daily_vehicle")
            vehicleAssignments = backend.toolController.dailyVehicleAssignments();
    }

    Component.onCompleted: refresh()
    onVisibleChanged: {
        if (visible && toolId === "daily_vehicle")
            refresh();
    }

    Connections {
        target: toolUsageHistory.backend.toolController

        function onUsageChanged(changedToolId) {
            if (changedToolId === toolUsageHistory.toolId)
                toolUsageHistory.refresh();
        }
    }

    Connections {
        target: toolUsageHistory.backend.sessionController

        function onSessionChanged() {
            if (toolUsageHistory.currentOperatorOnly)
                toolUsageHistory.refresh();
        }
    }

    contentItem: ColumnLayout {
        id: usageLayout
        spacing: 8

        ToolSectionTitle {
            text: "上次使用"
            markerColor: Design.successAction
            titleColor: Design.successHeading
        }

        ListView {
            id: usageList
            objectName: toolUsageHistory.toolId + "UsageList"
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? Math.min(contentHeight, Design.toolUsageMaxHeight) : 0
            Layout.minimumHeight: 0
            clip: true
            model: toolUsageHistory.usageModel
            visible: count > 0
            spacing: 8

            delegate: Item {
                id: usageRow
                required property int index
                required property string timeText
                required property string peopleText
                required property string resultText
                required property string tone
                width: ListView.view ? ListView.view.width : 0
                height: Design.toolUsageCardRowHeight * 3
                GridLayout {
                    anchors.fill: parent
                    columns: 2
                    rowSpacing: 1
                    columnSpacing: 8

                    ToolFieldLabel {
                        text: "時間"
                    }
                    Label {
                        Layout.fillWidth: true
                        text: usageRow.timeText
                        color: Design.strongText
                        font.pixelSize: Design.bodySize
                        elide: Text.ElideRight
                    }
                    ToolFieldLabel {
                        text: "人員"
                    }
                    Label {
                        Layout.fillWidth: true
                        text: usageRow.peopleText
                        color: Design.strongText
                        font.pixelSize: Design.bodySize
                        elide: Text.ElideRight
                    }
                    ToolFieldLabel {
                        text: "結果"
                    }
                    Label {
                        Layout.fillWidth: true
                        text: usageRow.resultText
                        color: usageRow.tone === "error" ? Design.dangerStrong : Design.success
                        font.pixelSize: Design.bodySize
                        font.bold: true
                        elide: Text.ElideRight
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: Design.borderWidth
                    visible: usageRow.index + 1 < usageList.count
                    color: Design.divider
                }
            }
        }

        Item {
            id: emptyUsageContent
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? Design.toolUsageCardRowHeight * 3 : 0
            visible: usageList.count === 0
            GridLayout {
                anchors.fill: parent
                columns: 2
                rowSpacing: 1
                columnSpacing: 8

                ToolFieldLabel {
                    text: "時間"
                }
                Label {
                    Layout.fillWidth: true
                    text: "尚無紀錄"
                    color: Design.strongText
                    font.pixelSize: Design.bodySize
                }
                ToolFieldLabel {
                    text: "人員"
                }
                Label {
                    Layout.fillWidth: true
                    text: "尚無紀錄"
                    color: Design.strongText
                    font.pixelSize: Design.bodySize
                }
                ToolFieldLabel {
                    text: "結果"
                }
                Label {
                    Layout.fillWidth: true
                    text: "尚無執行紀錄"
                    color: Design.muted
                    font.pixelSize: Design.bodySize
                    font.bold: true
                }
            }
        }

        ColumnLayout {
            objectName: "dailyVehicleAssignmentTable"
            Layout.fillWidth: true
            visible: toolUsageHistory.toolId === "daily_vehicle"
            spacing: 4

            ToolSectionTitle {
                text: "今日清點分派｜" + toolUsageHistory.vehicleAssignments.date
            }
            RowLayout {
                Layout.fillWidth: true
                visible: assignmentList.count > 0
                Repeater {
                    model: ["登入帳號", "定期保養", "隨車器材"]
                    delegate: ToolFieldLabel {
                        required property string modelData
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 1
                        text: modelData
                    }
                }
            }
            ListView {
                id: assignmentList
                objectName: "dailyVehicleAssignmentList"
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? Math.min(contentHeight, 140) : 0
                clip: true
                visible: count > 0
                model: toolUsageHistory.vehicleAssignments.rows
                ScrollBar.vertical: ScrollBar { }
                delegate: RowLayout {
                    id: assignmentRow
                    required property var modelData
                    width: assignmentList.width - 8
                    height: implicitHeight
                    Repeater {
                        model: [assignmentRow.modelData.account, assignmentRow.modelData.maintenance,
                                assignmentRow.modelData.equipment]
                        delegate: Label {
                            required property string modelData
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                            color: Design.strongText
                            font.pixelSize: Design.captionSize
                            text: modelData
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            bottomPadding: 4
                        }
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                visible: assignmentList.count === 0
                color: Design.muted
                text: "今日尚無清點分派紀錄"
                font.pixelSize: Design.captionSize
            }
        }

    }
}
