import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: dailyVehicleDialog
    required property var controller
    objectName: "dailyVehicleDialog"
    canClose: !dailyVehicleDialog.controller.isRunning

    contentItem: ToolPanelContent {
        ToolPanelHeader {
            text: "車輛保養清點"
            canClose: dailyVehicleDialog.canClose
            closeAction: function () {
                dailyVehicleDialog.close();
            }
        }
        ToolUsageHistory {
            backend: dailyVehicleDialog.hostWindow.backend
            toolId: "daily_vehicle"
        }
        ToolFormCard {
            contentItem: ColumnLayout {
                spacing: 8
                ToolSectionTitle {
                    text: "車輛保養設定"
                }

                Label {
                    objectName: "dailyVehiclePromptText"
                    Layout.fillWidth: true
                    text: "會使用目前登入帳密開啟瀏覽器。依序至車輛平日保養檢查清點、定期保養檢查頁，勾選保養（日、週、月、半年）；再至隨車器材清點頁，勾選清點。"
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                    wrapMode: Text.Wrap
                }
            }
        }
        Item {
            Layout.fillHeight: true
        }
        ToolStatusBar {
            objectName: "dailyVehicleStatusBar"
            text: dailyVehicleDialog.controller.statusText
            onDetailsRequested: function(message) {
                dailyVehicleDialog.hostWindow.showErrorDetails("車輛保養清點錯誤", message)
            }
        }
        ToolRunButton {
            objectName: "dailyVehicleRunButton"
            Layout.fillWidth: true
            text: dailyVehicleDialog.controller.isRunning ? "啟動中..." : "啟動登打"
            enabled: !dailyVehicleDialog.controller.isRunning
            onClicked: dailyVehicleDialog.controller.prepareRun()
        }
    }
}
