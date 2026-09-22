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
    required property var civilpowerPanel
    required property var monthlyBasePanel
    property bool dutyModeActive: false
    objectName: "dutyQuickToolsPanel"
    Layout.fillWidth: true
    implicitHeight: dutyQuickToolsLayout.implicitHeight
    visible: dutyQuickToolsPanel.backend.sessionController.isLoggedIn && dutyQuickToolsPanel.dutyModeActive
    color: Design.transparent
    border.width: Design.noBorderWidth
    radius: Design.noRadius

    function isSelected(panel) {
        return dutyQuickToolsPanel.hostWindow.activeToolSidePanel === panel && panel.opened
    }

    ColumnLayout {
        id: dutyQuickToolsLayout
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Rectangle {
                id: dailyMonthlyOperationCard
                objectName: "dailyMonthlyOperationCard"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: dailyMonthlyOperationLayout.implicitHeight + 20
                radius: Design.radius
                color: Design.panel
                border.width: Design.borderWidth
                border.color: dutyQuickToolsPanel.hostWindow.border

                ColumnLayout {
                    id: dailyMonthlyOperationLayout
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8

                    Item {
                        id: dailyOperationCard
                        objectName: "dailyOperationCard"
                        Layout.fillWidth: true
                        implicitHeight: dailyOperationLayout.implicitHeight

                        RowLayout {
                            id: dailyOperationLayout
                            anchors.fill: parent
                            spacing: 8

                            Item {
                                id: dailyOperationLabelArea
                                objectName: "dailyOperationLabelArea"
                                Layout.preferredWidth: 58
                                Layout.minimumWidth: 58
                                Layout.alignment: Qt.AlignVCenter
                                implicitHeight: 40

                                Label {
                                    id: dailyOperationLabel
                                    objectName: "dailyOperationLabel"
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "每日作業"
                                    color: Design.blueHover
                                    font.bold: true
                                }
                                Label {
                                    objectName: "dailyOperationCompletionLabel"
                                    anchors.left: parent.left
                                    width: dailyOperationLabel.width
                                    anchors.bottom: parent.bottom
                                    text: "已完成 " + dutyQuickToolsPanel.backend.toolController.dailyCompletionCount + " / 2"
                                    color: dutyQuickToolsPanel.backend.toolController.dailyCompletionCount === 2
                                           ? Design.successText
                                           : Design.muted
                                    font.pixelSize: Design.dutyQuickToolCompletionSize
                                    horizontalAlignment: Text.AlignHCenter
                                }
                            }

                            AppleButton {
                                objectName: "quickDutySheetToolButton"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Layout.preferredWidth: 1
                                leftPadding: 4
                                rightPadding: 4
                                font.pixelSize: Design.captionSize
                                text: "勤務表登打"
                                tone: "info"
                                enabled: !dutyQuickToolsPanel.backend.readOnlyAcceptance
                                showStatusLight: true
                                statusLightOn: !dutyQuickToolsPanel.backend.toolController.dutySheetCompleted
                                statusLightObjectName: "quickDutySheetCompletionLight"
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
                                leftPadding: 4
                                rightPadding: 4
                                font.pixelSize: Design.captionSize
                                text: "車輛保養"
                                tone: "info"
                                enabled: !dutyQuickToolsPanel.backend.readOnlyAcceptance
                                showStatusLight: true
                                statusLightOn: !dutyQuickToolsPanel.backend.toolController.dailyVehicleCompleted
                                statusLightObjectName: "quickDailyVehicleCompletionLight"
                                selectedState: dutyQuickToolsPanel.isSelected(dutyQuickToolsPanel.dailyVehiclePanel)
                                onClicked: {
                                    dutyQuickToolsPanel.backend.dailyVehicleController.loadDefaults()
                                    dutyQuickToolsPanel.dailyVehiclePanel.open()
                                }
                            }
                        }
                    }

                    Item {
                        id: monthlyOperationCard
                        objectName: "monthlyOperationCard"
                        Layout.fillWidth: true
                        implicitHeight: monthlyOperationLayout.implicitHeight

                        RowLayout {
                            id: monthlyOperationLayout
                            anchors.fill: parent
                            spacing: 8

                            Label {
                                objectName: "monthlyOperationLabel"
                                Layout.preferredWidth: 58
                                Layout.minimumWidth: 58
                                Layout.alignment: Qt.AlignVCenter
                                text: "每月作業"
                                color: Design.monthlyText
                                font.bold: true
                            }
                            AppleButton {
                                objectName: "quickRestTimeToolButton"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Layout.preferredWidth: 1
                                leftPadding: 4
                                rightPadding: 4
                                font.pixelSize: Design.captionSize
                                text: "休息時間登打"
                                tone: "monthly"
                                enabled: !dutyQuickToolsPanel.backend.readOnlyAcceptance
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
                                leftPadding: 4
                                rightPadding: 4
                                font.pixelSize: Design.captionSize
                                text: "勤務基準表登打"
                                tone: "monthly"
                                enabled: !dutyQuickToolsPanel.backend.readOnlyAcceptance
                                selectedState: dutyQuickToolsPanel.isSelected(dutyQuickToolsPanel.monthlyBasePanel)
                                onClicked: {
                                    dutyQuickToolsPanel.backend.restMonthlyController.loadMonthlyDefaults()
                                    dutyQuickToolsPanel.monthlyBasePanel.open()
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                objectName: "otherToolsCard"
                Layout.preferredWidth: 130
                Layout.minimumWidth: 130
                implicitHeight: dailyMonthlyOperationCard.implicitHeight
                radius: Design.radius
                color: Design.panel
                border.width: Design.borderWidth
                border.color: dutyQuickToolsPanel.hostWindow.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8
                    AppleButton {
                        objectName: "quickRescueVideoToolButton"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        leftPadding: 4
                        rightPadding: 4
                        font.pixelSize: Design.captionSize
                        text: "救護行車紀錄器"
                        tone: "review"
                        enabled: !dutyQuickToolsPanel.backend.readOnlyAcceptance
                        selectedState: dutyQuickToolsPanel.rescueVideoWindow.visible
                        onClicked: {
                            if (!dutyQuickToolsPanel.rescueVideoWindow.visible)
                                dutyQuickToolsPanel.backend.rescueVideoController.loadDefaults()
                            dutyQuickToolsPanel.rescueVideoWindow.open()
                        }
                    }
                    AppleButton {
                        objectName: "quickCivilpowerToolButton"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        leftPadding: 4
                        rightPadding: 4
                        font.pixelSize: Design.captionSize
                        text: "民力系統"
                        tone: "review"
                        enabled: !dutyQuickToolsPanel.backend.readOnlyAcceptance
                        selectedState: dutyQuickToolsPanel.isSelected(dutyQuickToolsPanel.civilpowerPanel)
                        onClicked: {
                            dutyQuickToolsPanel.backend.civilpowerController.loadDefaults()
                            dutyQuickToolsPanel.civilpowerPanel.open()
                        }
                    }
                }
            }
        }

        ToolStatusBar {
            objectName: "toolCenterStatusBar"
            onlyShowErrors: true
            text: dutyQuickToolsPanel.backend.toolController.statusText
            onDetailsRequested: function(message) {
                dutyQuickToolsPanel.hostWindow.showErrorDetails("工具中心錯誤", message)
            }
        }
    }
}
