pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"
import "../components"

Window {
    id: updateWindow
    objectName: "updateProgressWindow"
    required property var controller
    readonly property var view: controller.updateView
    readonly property bool busy: Boolean(view.busy)
    readonly property bool reduceMotion: controller.reducedMotion
    width: 460
    height: busy ? 280 : 344
    minimumWidth: width
    maximumWidth: width
    minimumHeight: busy ? 280 : 344
    maximumHeight: busy ? 280 : 344
    visible: Boolean(view.visible)
    title: "SinpoSmart 更新"
    flags: Qt.Window | Qt.FramelessWindowHint
    modality: Qt.WindowModal
    color: Design.transparent

    onClosing: function(close) {
        close.accepted = !updateWindow.busy
        if (close.accepted)
            updateWindow.controller.dismissUpdateWindow()
    }

    onVisibleChanged: {
        if (visible) {
            requestActivate()
            raise()
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: Design.radiusSheet
        color: Design.panel
        border.width: Design.borderWidth
        border.color: Design.border

        Item {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 52
            DragHandler {
                target: null
                onActiveChanged: if (active) updateWindow.startSystemMove()
            }
        }

        Row {
            x: 24
            y: 21
            spacing: 10
            Canvas {
                width: 18
                height: 24
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    ctx.strokeStyle = Design.blue
                    ctx.lineWidth = 1.7
                    ctx.lineCap = "round"
                    ctx.beginPath()
                    ctx.arc(9, 12, 6.5, 0.45, Math.PI * 1.85)
                    ctx.stroke()
                    ctx.beginPath()
                    ctx.moveTo(10.5, 6.8)
                    ctx.lineTo(15, 8.8)
                    ctx.lineTo(15.2, 4.2)
                    ctx.stroke()
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "SinpoSmart 更新"
                color: Design.secondaryText
                font.pixelSize: Design.labelSize
                font.weight: Font.Medium
            }
        }

        Text {
            objectName: "updateHeading"
            x: 24
            y: 66
            width: parent.width - 48
            text: updateWindow.view.title
            color: Design.text
            font.pixelSize: Design.heroTitleSize
            font.weight: Font.DemiBold
            Accessible.role: Accessible.Heading
            Accessible.name: text
        }

        Text {
            x: 24
            y: 105
            width: parent.width - 48
            height: 42
            text: updateWindow.view.subtitle
            color: Design.muted
            font.pixelSize: Design.bodySize
            wrapMode: Text.Wrap
        }

        RowLayout {
            x: 24
            y: 153
            width: parent.width - 48
            height: 36
            spacing: 12
            Text {
                objectName: "updatePhaseLabel"
                Layout.fillWidth: true
                text: updateWindow.view.detail
                color: updateWindow.view.phase === "failed" ? Design.dangerStrong : Design.secondaryText
                font.pixelSize: Design.bodySize
                wrapMode: Text.Wrap
            }
            Text {
                objectName: "updatePercentLabel"
                visible: updateWindow.view.progress >= 0
                text: Math.max(0, updateWindow.view.progress) + "%"
                color: updateWindow.view.phase === "completed" ? Design.success : Design.blue
                font.pixelSize: Design.displaySize
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
            }
        }

        ProgressBar {
            id: updateProgress
            objectName: "updateProgressBar"
            x: 24
            y: 197
            width: parent.width - 48
            height: 8
            visible: updateWindow.busy || updateWindow.view.progress >= 0
            from: 0
            to: 100
            value: Math.max(0, updateWindow.view.progress)
            indeterminate: updateWindow.busy && updateWindow.view.progress < 0
            Accessible.name: updateWindow.view.detail
            Accessible.description: indeterminate ? "處理中" : Math.round(value) + "%"
            background: Rectangle {
                radius: height / 2
                color: Design.softActionHover
            }
            contentItem: Item {
                clip: true
                Rectangle {
                    id: progressFill
                    width: updateProgress.indeterminate ? parent.width * 0.28 : parent.width * updateProgress.position
                    height: parent.height
                    radius: height / 2
                    color: updateWindow.view.phase === "completed" ? Design.success : Design.blue
                    Behavior on width {
                        enabled: !updateWindow.reduceMotion && !updateProgress.indeterminate
                        SmoothedAnimation { duration: Design.sidePanelTransitionDuration; velocity: -1 }
                    }
                    SequentialAnimation on x {
                        running: updateProgress.indeterminate && updateWindow.visible && !updateWindow.reduceMotion
                        loops: Animation.Infinite
                        NumberAnimation { from: 0; to: updateProgress.width - progressFill.width; duration: 850; easing.type: Easing.InOutSine }
                        NumberAnimation { from: updateProgress.width - progressFill.width; to: 0; duration: 850; easing.type: Easing.InOutSine }
                        onStopped: progressFill.x = 0
                    }
                }
            }
        }

        Rectangle {
            x: 24
            y: 225
            width: parent.width - 48
            height: 1
            color: Design.divider
        }

        Text {
            x: 24
            y: 239
            width: parent.width - 48
            text: updateWindow.view.footer
            color: Design.muted
            font.pixelSize: Design.captionSize
            wrapMode: Text.Wrap
        }

        RowLayout {
            x: 24
            y: 286
            width: parent.width - 48
            spacing: 10
            AppleButton {
                objectName: "updateDiagnosticsButton"
                visible: updateWindow.view.diagnosticPath.length > 0
                text: "查看紀錄"
                tone: "ghost"
                onClicked: updateWindow.controller.openUpdateDiagnostics()
            }
            Item { Layout.fillWidth: true }
            AppleButton {
                objectName: "updateDismissButton"
                visible: !updateWindow.busy
                text: updateWindow.view.canInstall ? "稍後" : "關閉"
                onClicked: updateWindow.controller.dismissUpdateWindow()
            }
            AppleButton {
                objectName: "updateInstallButton"
                visible: Boolean(updateWindow.view.canInstall)
                text: "登出並更新"
                tone: "primary"
                onClicked: updateWindow.controller.launchUpdate()
            }
        }
    }
}
