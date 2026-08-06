pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

Rectangle {
    id: dutyTaskArea
    required property var backend
    required property var hostWindow
    property int modeIndex: 0
    signal auditDetailRequested(string fullDetailText)

    objectName: "dutyTaskArea"
    Layout.fillWidth: true
    Layout.fillHeight: true
    visible: dutyTaskArea.backend.sessionController.isLoggedIn && (dutyTaskArea.modeIndex === 1 || dutyTaskArea.modeIndex === 0)
    radius: Design.radius
    color: Design.panel
    border.color: dutyTaskArea.hostWindow.border

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        spacing: 4

        RowLayout {
            id: dutyTaskHeader
            objectName: "dutyTaskHeader"
            Layout.fillWidth: true
            Layout.leftMargin: Design.dutyTaskGridInset
            Layout.rightMargin: Design.dutyTaskGridInset
            Layout.preferredHeight: 30
            visible: dutyTaskArea.modeIndex === 0
            spacing: 0

            Label {
                objectName: "dutyTaskTimeHeaderCell"
                Layout.preferredWidth: Design.dutyTaskTimeWidth
                text: "時間"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                objectName: "dutyTaskSystemHeaderCell"
                Layout.preferredWidth: Design.dutyTaskSystemWidth
                text: "類型"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                objectName: "dutyTaskDetailHeaderCell"
                Layout.fillWidth: true
                text: "任務內容"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                objectName: "dutyTaskPeopleHeaderCell"
                Layout.preferredWidth: Design.dutyTaskPeopleWidth
                text: "人員"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                objectName: "dutyTaskStatusHeaderCell"
                Layout.preferredWidth: Design.taskStatusWidth
                text: "狀態"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
        }

        RowLayout {
            id: auditTaskHeader
            objectName: "auditTaskHeader"
            Layout.fillWidth: true
            Layout.leftMargin: Design.dutyTaskGridInset
            Layout.rightMargin: Design.dutyTaskGridInset
            Layout.preferredHeight: 30
            visible: dutyTaskArea.modeIndex === 1
            spacing: 0
            Label {
                Layout.preferredWidth: Design.auditTaskComparisonWidth
                text: "比對"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                Layout.preferredWidth: Design.auditTaskTimeWidth
                text: "登打時間"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                Layout.preferredWidth: Design.auditTaskActorWidth
                text: "登打人"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                Layout.preferredWidth: Design.auditTaskTargetWidth
                text: "對象/服勤"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                Layout.preferredWidth: Design.auditTaskSystemWidth
                text: "類型"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                Layout.fillWidth: true
                text: "內容"
                color: dutyTaskArea.hostWindow.ink
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
        }

        ListView {
            id: taskList
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 3
            clip: true
            bottomMargin: selectedTaskActions.visible ? selectedTaskActions.height + 20 : 0
            model: dutyTaskArea.modeIndex === 0 ? dutyTaskArea.backend.dutyController.taskModel : dutyTaskArea.backend.dutyController.auditModel

            delegate: DutyTaskCard {
                id: taskRow
                objectName: dutyTaskArea.modeIndex === 1 ? "auditTaskRow" : "dutyTaskRow"
                required property int taskIndex
                required property string timeText
                required property string systemText
                required property string detailText
                required property string peopleText
                required property string statusText
                required property string statusTone
                required property string actorText
                required property string targetText
                required property string comparisonText
                required property string group
                required property string fullDetailText
                required property bool selected

                width: taskList.width
                dutyMode: dutyTaskArea.modeIndex === 0
                selectedState: taskRow.selected
                tone: taskRow.statusTone

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (dutyTaskArea.modeIndex === 0) {
                            dutyTaskArea.backend.dutyController.toggleTaskSelection(taskRow.taskIndex);
                        } else {
                            dutyTaskArea.auditDetailRequested(taskRow.fullDetailText);
                        }
                    }
                }

                RowLayout {
                    visible: dutyTaskArea.modeIndex === 0
                    anchors.fill: parent
                    anchors.leftMargin: Design.dutyTaskGridInset
                    anchors.rightMargin: Design.dutyTaskGridInset
                    spacing: 0
                    Label {
                        objectName: "dutyTaskTimeCell"
                        Layout.preferredWidth: Design.dutyTaskTimeWidth
                        text: taskRow.timeText
                        color: dutyTaskArea.hostWindow.ink
                        font.bold: true
                        font.pixelSize: Design.labelSize
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    Label {
                        objectName: "dutyTaskSystemCell"
                        Layout.preferredWidth: Design.dutyTaskSystemWidth
                        text: taskRow.systemText
                        color: taskRow.systemText === "出入" ? Design.blueHover : Design.success
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Label {
                        objectName: "dutyTaskDetailCell"
                        Layout.fillWidth: true
                        text: taskRow.detailText
                        color: dutyTaskArea.hostWindow.ink
                        elide: Text.ElideRight
                    }
                    Label {
                        objectName: "dutyTaskPeopleCell"
                        Layout.preferredWidth: Design.dutyTaskPeopleWidth
                        text: taskRow.peopleText
                        color: dutyTaskArea.hostWindow.ink
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    DutyTaskStatusPill {
                        Layout.preferredWidth: implicitWidth
                        Layout.preferredHeight: implicitHeight
                        tone: taskRow.statusTone
                        statusText: taskRow.statusText
                    }
                }

                RowLayout {
                    visible: dutyTaskArea.modeIndex === 1
                    anchors.fill: parent
                    anchors.leftMargin: Design.dutyTaskGridInset
                    anchors.rightMargin: Design.dutyTaskGridInset
                    spacing: 0
                    Label {
                        Layout.preferredWidth: Design.auditTaskComparisonWidth
                        text: taskRow.comparisonText
                        color: taskRow.statusTone === "triggered" ? Design.successText : Design.warningText
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.preferredWidth: Design.auditTaskTimeWidth
                        text: taskRow.timeText
                        color: dutyTaskArea.hostWindow.ink
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.preferredWidth: Design.auditTaskActorWidth
                        text: taskRow.actorText
                        color: dutyTaskArea.hostWindow.ink
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.preferredWidth: Design.auditTaskTargetWidth
                        text: taskRow.targetText
                        color: dutyTaskArea.hostWindow.ink
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.preferredWidth: Design.auditTaskSystemWidth
                        text: taskRow.systemText
                        color: dutyTaskArea.hostWindow.accent
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.fillWidth: true
                        text: taskRow.detailText
                        color: dutyTaskArea.hostWindow.ink
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                }
            }

            Rectangle {
                id: auditEmptyState
                objectName: "auditEmptyState"
                parent: taskList
                anchors.centerIn: parent
                width: Math.min(taskList.width - 32, 360)
                height: auditEmptyContent.implicitHeight + 28
                visible: taskList.count === 0 && !dutyTaskArea.backend.dutyController.isRefreshing
                radius: Design.radius
                color: Design.comboHover
                border.color: Design.comboBorder
                z: 1

                ColumnLayout {
                    id: auditEmptyContent
                    anchors.fill: parent
                    anchors.margins: 14

                    Label {
                        Layout.fillWidth: true
                        text: dutyTaskArea.modeIndex === 1 ? "此日期尚無審核任務" : "目前沒有勤務任務"
                        color: Design.infoText
                        font.pixelSize: Design.sectionTitleSize
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
        }
    }

    Rectangle {
        id: selectedTaskActions
        objectName: "selectedTaskActions"
        visible: dutyTaskArea.modeIndex === 0
                 && dutyTaskArea.backend.sessionController.isLoggedIn
                 && dutyTaskArea.backend.dutyController.selectedTaskCount > 0
                 && !dutyTaskArea.backend.readOnlyAcceptance
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        implicitWidth: selectedTaskActionRow.implicitWidth + 16
        implicitHeight: selectedTaskActionRow.implicitHeight + 16
        radius: Design.radiusMedium
        color: Design.panelTint
        border.width: Design.borderWidth
        border.color: Design.infoBorder
        z: 2

        RowLayout {
            id: selectedTaskActionRow
            anchors.centerIn: parent
            spacing: 8

            DutyActionButton {
                objectName: "manualPauseButton"
                text: "手動暫停"
                tone: "warningStrong"
                enabled: dutyTaskArea.backend.dutyController.canAdjustSelectedSchedule
                onClicked: dutyTaskArea.backend.dutyController.pauseSelectedTasks()
            }
            DutyActionButton {
                objectName: "resumeScheduleButton"
                text: "繼續排程"
                tone: "success"
                enabled: dutyTaskArea.backend.dutyController.canAdjustSelectedSchedule
                onClicked: dutyTaskArea.backend.dutyController.resumeSelectedTasks()
            }
            DutyActionButton {
                objectName: "manualSubmitButton"
                text: "手動登打"
                tone: "primary"
                emphasizedBorder: true
                enabled: dutyTaskArea.backend.dutyController.canManualSubmitSelected
                onClicked: dutyTaskArea.backend.dutyController.prepareManualSubmission()
            }
        }
    }
}
