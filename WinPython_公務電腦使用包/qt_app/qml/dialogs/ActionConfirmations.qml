import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: actionConfirmations
    required property var hostWindow
    required property var backend
    property string updateStatusText: ""
    property string statusDialogTitle: "檢查更新"

    anchors.fill: parent

    function openLogoutConfirmation() {
        logoutConfirmation.open()
    }

    AppleDialog {
        id: logoutConfirmation
        objectName: "logoutConfirmation"
        anchors.centerIn: parent
        width: Math.min(actionConfirmations.hostWindow.width - 72, 460)
        modal: true
        title: "確認登出"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: actionConfirmations.backend.updateController.logoutActionText
        onAccepted: {
            if (actionConfirmations.backend.sessionController.isLoggedIn) {
                actionConfirmations.backend.requestLogout()
            }
        }

        Label {
            width: parent.width
            text: actionConfirmations.backend.updateController.logoutActionText === "登出並更新"
                  ? "確定要登出目前的值班帳號並套用已準備的更新嗎？"
                  : "確定要登出目前的值班帳號嗎？"
            color: actionConfirmations.hostWindow.ink
            wrapMode: Text.Wrap
        }
    }

    function openManualSubmissionConfirmation() {
        manualSubmissionConfirmation.open()
    }

    function openExternalReturnManualSubmissionConfirmation() {
        externalReturnManualSubmissionConfirmation.open()
    }

    function openCredentialSyncConfirmation() {
        credentialSyncConfirmation.open()
    }

    function openRestMonthlyConfirmation() {
        restMonthlyConfirmation.open()
    }

    function openDailyVehicleConfirmation() {
        dailyVehicleConfirmation.open()
    }

    function openDiagnosticsStatus(message) {
        statusDialogTitle = "問題包"
        updateStatusText = String(message || "問題包處理完成。")
        updateStatusDialog.open()
    }

    AppleDialog {
        id: manualSubmissionConfirmation
        objectName: "manualSubmissionConfirmation"
        anchors.centerIn: parent
        width: Math.min(actionConfirmations.hostWindow.width - 72, 500)
        modal: true
        title: "確認手動登打"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "開始登打"
        onAccepted: {
            if (!actionConfirmations.backend.readOnlyAcceptance) {
                actionConfirmations.backend.dutyController.confirmManualSubmission()
            }
        }
        onRejected: actionConfirmations.backend.dutyController.cancelManualSubmission()

        Label {
            width: parent.width
            text: actionConfirmations.backend.dutyController.manualConfirmationSummary
            color: actionConfirmations.hostWindow.ink
            wrapMode: Text.Wrap
        }
    }

    AppleDialog {
        id: externalReturnManualSubmissionConfirmation
        objectName: "externalReturnManualSubmissionConfirmation"
        anchors.centerIn: parent
        width: Math.min(actionConfirmations.hostWindow.width - 72, 500)
        modal: true
        title: "確認返隊手動登打"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "確認登打"
        onAccepted: {
            if (!actionConfirmations.backend.readOnlyAcceptance) {
                actionConfirmations.backend.dutyController.confirmExternalReturnManualSubmission()
            }
        }
        onRejected: actionConfirmations.backend.dutyController.cancelExternalReturnManualSubmission()

        Label {
            width: parent.width
            text: actionConfirmations.backend.dutyController.externalReturnConfirmationSummary
            color: actionConfirmations.hostWindow.ink
            wrapMode: Text.Wrap
        }
    }

    AppleDialog {
        id: updateStatusDialog
        anchors.centerIn: parent
        width: Math.min(actionConfirmations.hostWindow.width - 72, 460)
        modal: true
        title: actionConfirmations.statusDialogTitle
        standardButtons: Dialog.Close

        ColumnLayout {
            width: parent.width
            spacing: 8

            Label {
                objectName: "updateStatusTextLabel"
                Layout.fillWidth: true
                visible: !updateStatusErrorBar.visible
                text: actionConfirmations.updateStatusText
                color: actionConfirmations.hostWindow.ink
                wrapMode: Text.Wrap
            }

            ToolStatusBar {
                id: updateStatusErrorBar
                objectName: "updateStatusErrorBar"
                onlyShowErrors: true
                text: actionConfirmations.updateStatusText
                onDetailsRequested: function(message) {
                    actionConfirmations.hostWindow.showErrorDetails(
                        actionConfirmations.statusDialogTitle + "錯誤",
                        message
                    )
                }
            }
        }
    }

    AppleDialog {
        id: credentialSyncConfirmation
        anchors.centerIn: parent
        width: Math.min(actionConfirmations.hostWindow.width - 72, 540)
        modal: true
        title: "確認同步帳密"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "開始同步"
        onAccepted: {
            if (!actionConfirmations.backend.readOnlyAcceptance) {
                actionConfirmations.backend.sessionController.syncSavedAccounts()
            }
        }

        Label {
            width: parent.width
            text: "將透過已設定的 NAS relay 傳送這台電腦已儲存的勤務系統帳號、密碼與人員資料，供指定公務電腦取用。是否繼續？"
            color: actionConfirmations.hostWindow.ink
            wrapMode: Text.Wrap
        }
    }

    AppleDialog {
        id: restMonthlyConfirmation
        objectName: "restMonthlyConfirmation"
        anchors.centerIn: parent
        width: Math.min(actionConfirmations.hostWindow.width - 72, 460)
        modal: true
        title: "確認正式登打"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "開始登打"
        onAccepted: {
            if (!actionConfirmations.backend.readOnlyAcceptance) {
                actionConfirmations.backend.restMonthlyController.confirmRun()
            }
        }
        onRejected: actionConfirmations.backend.restMonthlyController.cancelPendingRun()

        Label {
            width: parent.width
            text: actionConfirmations.backend.restMonthlyController.confirmationSummary
            color: actionConfirmations.hostWindow.ink
            wrapMode: Text.Wrap
        }
    }

    AppleDialog {
        id: dailyVehicleConfirmation
        objectName: "dailyVehicleConfirmation"
        anchors.centerIn: parent
        width: Math.min(actionConfirmations.hostWindow.width - 72, 460)
        modal: true
        title: "車輛保養清點"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "開始登打"
        onAccepted: {
            if (!actionConfirmations.backend.readOnlyAcceptance) {
                actionConfirmations.backend.dailyVehicleController.confirmRun()
            }
        }
        onRejected: actionConfirmations.backend.dailyVehicleController.cancelPendingRun()

        Label {
            width: parent.width
            text: actionConfirmations.backend.dailyVehicleController.confirmationSummary
            color: actionConfirmations.hostWindow.ink
            wrapMode: Text.Wrap
        }
    }
}
