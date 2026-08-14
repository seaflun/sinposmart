import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ColumnLayout {
    id: auditFilterPanel
    required property var backend
    required property var hostWindow
    property bool auditModeActive: false
    objectName: "auditFilterPanel"
    Layout.fillWidth: true
    visible: auditFilterPanel.auditModeActive
             && auditFilterPanel.backend.sessionController.isLoggedIn
    spacing: 8

    AppleCalendarButton {
        id: auditDateCalendar
        objectName: "auditDateCalendarButton"
        triggerOnly: true
        anchorItem: auditDateField
        popupParent: auditFilterPanel.hostWindow.contentItem
        dateText: auditFilterPanel.backend.dutyController.targetDateText
        dateFormat: "roc"
        enabled: !auditFilterPanel.backend.dutyController.isRefreshing
        onDateSelected: function(value) {
            auditFilterPanel.backend.refreshAuditDate(value)
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 10

        Rectangle {
            objectName: "auditDateCard"
            Layout.fillWidth: true
            implicitHeight: 108
            radius: Design.radius
            color: Design.comboHover
            border.color: Design.comboBorder

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4

                Label {
                    text: "日期切換"
                    color: Design.infoText
                    font.pixelSize: Design.controlSize
                    font.bold: true
                }
                Label {
                    text: "勤務日期"
                    color: Design.secondaryText
                    font.pixelSize: Design.labelSize
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    AppleTextField {
                        id: auditDateField
                        objectName: "auditDateField"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 84
                        text: auditFilterPanel.backend.dutyController.targetDateText
                        readOnly: true
                        enabled: !auditFilterPanel.backend.dutyController.isRefreshing
                        Accessible.name: "選擇勤務日期"
                        clickAction: function() {
                            auditDateCalendar.openForCurrentDate()
                        }
                    }
                    AppleButton {
                        objectName: "auditPreviousDayButton"
                        implicitWidth: 38
                        enabled: !auditFilterPanel.backend.dutyController.isRefreshing
                        text: "<"
                        Accessible.name: "前一天"
                        onClicked: auditFilterPanel.backend.shiftAuditDate(-1)
                    }
                    AppleButton {
                        objectName: "auditNextDayButton"
                        implicitWidth: 38
                        enabled: !auditFilterPanel.backend.dutyController.isRefreshing
                        text: ">"
                        Accessible.name: "後一天"
                        onClicked: auditFilterPanel.backend.shiftAuditDate(1)
                    }
                    PrimaryButton {
                        objectName: "auditRefreshButton"
                        Layout.minimumWidth: Design.auditRefreshButtonWidth
                        Layout.preferredWidth: Design.auditRefreshButtonWidth
                        Layout.maximumWidth: Design.auditRefreshButtonWidth
                        implicitHeight: 34
                        enabled: !auditFilterPanel.backend.dutyController.isRefreshing
                        text: auditFilterPanel.backend.dutyController.isRefreshing ? "更新中…" : "重新查詢"
                        onClicked: auditFilterPanel.backend.refreshAuditLiveData()
                    }
                }
            }
        }

        Rectangle {
            objectName: "auditFilterCard"
            Layout.fillWidth: true
            implicitHeight: 108
            radius: Design.radius
            color: Design.comboHover
            border.color: Design.comboBorder

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4

                Label {
                    text: "篩選條件"
                    color: Design.infoText
                    font.pixelSize: Design.controlSize
                    font.bold: true
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: "狀態"
                        color: auditFilterPanel.hostWindow.muted
                        font.pixelSize: Design.labelSize
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "類型"
                        color: auditFilterPanel.hostWindow.muted
                        font.pixelSize: Design.labelSize
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    AppleComboBox {
                        objectName: "auditStatusFilter"
                        Layout.fillWidth: true
                        model: ["需處理", "全部", "已登打", "手動", "尚未到點", "疑似異動", "時間近似", "人工確認", "未返隊暫停", "外勤休息手動"]
                        currentIndex: Math.max(0, model.indexOf(auditFilterPanel.backend.dutyController.auditStatusFilter))
                        onActivated: auditFilterPanel.backend.dutyController.setAuditStatusFilter(currentText)
                    }
                    AppleComboBox {
                        objectName: "auditKindFilter"
                        Layout.fillWidth: true
                        model: ["全部", "工作", "出入", "案件工作"]
                        currentIndex: Math.max(0, model.indexOf(auditFilterPanel.backend.dutyController.auditKindFilter))
                        onActivated: auditFilterPanel.backend.dutyController.setAuditKindFilter(currentText)
                    }
                }
            }
        }
    }

    RowLayout {
        id: auditRefreshStatusArea
        Layout.fillWidth: true
        visible: auditRefreshStatusText.text.length > 0
        Layout.preferredHeight: visible ? auditRefreshStatusText.implicitHeight : 0
        Layout.minimumHeight: Layout.preferredHeight
        Layout.maximumHeight: Layout.preferredHeight

        Label {
            id: auditRefreshStatusText
            objectName: "auditRefreshStatusText"
            Layout.preferredWidth: 360
            Layout.maximumWidth: 360
            text: auditFilterPanel.backend.dutyController.scheduleStatus
            color: /(失敗|錯誤|逾時|登入)/.test(text) ? Design.dangerStrong : Design.muted
            font.pixelSize: Design.captionSize
            horizontalAlignment: Text.AlignLeft
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
            activeFocusOnTab: truncated
            Accessible.name: text

            HoverHandler {
                id: auditRefreshStatusHover
            }

            ToolTip.visible: auditRefreshStatusText.truncated
                                 && (auditRefreshStatusHover.hovered || auditRefreshStatusText.activeFocus)
            ToolTip.text: auditRefreshStatusText.text
            ToolTip.delay: 400
            ToolTip.timeout: 10000
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 6

        AuditSummaryCard {
            objectName: "auditTodoSummaryCard"
            Layout.fillWidth: true
            summaryText: "未找到 " + auditFilterPanel.backend.dutyController.auditTodoCount
            tone: "todo"
        }
        AuditSummaryCard {
            objectName: "auditReviewSummaryCard"
            Layout.fillWidth: true
            summaryText: "人工確認 " + auditFilterPanel.backend.dutyController.auditReviewCount
            tone: "review"
        }
        AuditSummaryCard {
            objectName: "auditReadySummaryCard"
            Layout.fillWidth: true
            summaryText: "尚未到點 " + auditFilterPanel.backend.dutyController.auditReadyCount
            tone: "ready"
        }
        AuditSummaryCard {
            objectName: "auditDoneSummaryCard"
            Layout.fillWidth: true
            summaryText: "已登打 " + auditFilterPanel.backend.dutyController.auditDoneCount
            tone: "done"
        }
    }
}
