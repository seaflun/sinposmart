import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

Rectangle {
    id: dutyQuickToolsPanel
    required property var backend
    required property var hostWindow
    required property var dutySheetPanel
    required property var dailyVehiclePanel
    required property var rescueVideoWindow
    required property var restTimePanel
    required property var monthlyBasePanel
    property bool dutyModeActive: false
    objectName: "dutyQuickToolsPanel"
    Layout.fillWidth: true
    implicitHeight: dutyQuickToolsLayout.implicitHeight + 20
    visible: dutyQuickToolsPanel.backend.sessionController.isLoggedIn && dutyQuickToolsPanel.dutyModeActive
    radius: Design.radius
    color: Design.panel
    border.width: Design.borderWidth
    border.color: dutyQuickToolsPanel.hostWindow.border

    function isSelected(panel) {
        return dutyQuickToolsPanel.hostWindow.activeToolSidePanel === panel && panel.opened
    }

    ColumnLayout {
        id: dutyQuickToolsLayout
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label {
                Layout.preferredWidth: 58
                text: "每日作業"
                color: Design.blueHover
                font.bold: true
            }
            AppleButton {
                objectName: "quickDutySheetToolButton"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                text: "勤務表登打"
                tone: "info"
                selectedState: dutyQuickToolsPanel.isSelected(dutyQuickToolsPanel.dutySheetPanel)
                onClicked: {
                    dutyQuickToolsPanel.backend.dutySheetController.loadDefaults()
                    dutyQuickToolsPanel.dutySheetPanel.open()
                }
            }
            AppleButton {
                objectName: "quickDailyVehicleToolButton"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                text: "車輛保養清點"
                tone: "info"
                selectedState: dutyQuickToolsPanel.isSelected(dutyQuickToolsPanel.dailyVehiclePanel)
                onClicked: {
                    dutyQuickToolsPanel.backend.dailyVehicleController.loadDefaults()
                    dutyQuickToolsPanel.dailyVehiclePanel.open()
                }
            }
            AppleButton {
                objectName: "quickRescueVideoToolButton"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                text: "行車紀錄器"
                tone: "warning"
                selectedState: dutyQuickToolsPanel.rescueVideoWindow.visible
                onClicked: {
                    dutyQuickToolsPanel.backend.rescueVideoController.loadDefaults()
                    dutyQuickToolsPanel.rescueVideoWindow.open()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label {
                Layout.preferredWidth: 58
                text: "每月作業"
                color: Design.monthlyText
                font.bold: true
            }
            AppleButton {
                objectName: "quickRestTimeToolButton"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                text: "休息時間登打"
                tone: "monthly"
                selectedState: dutyQuickToolsPanel.isSelected(dutyQuickToolsPanel.restTimePanel)
                onClicked: {
                    dutyQuickToolsPanel.backend.restMonthlyController.loadRestDefaults()
                    dutyQuickToolsPanel.restTimePanel.open()
                }
            }
            AppleButton {
                objectName: "quickMonthlyBaseToolButton"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                text: "勤務基準表登打"
                tone: "monthly"
                selectedState: dutyQuickToolsPanel.isSelected(dutyQuickToolsPanel.monthlyBasePanel)
                onClicked: {
                    dutyQuickToolsPanel.backend.restMonthlyController.loadMonthlyDefaults()
                    dutyQuickToolsPanel.monthlyBasePanel.open()
                }
            }
        }
    }
}
