pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components"
import "../styles"

Window {
    id: rescueVideoWindow
    required property var hostWindow
    required property var controller
    required property var errorHandler
    property var nativeTitleBarConfigurator: null
    objectName: "rescueVideoDialog"
    visible: false
    width: Design.rescueWindowWidth
    height: Design.rescueWindowHeight + Design.appTitleBarHeight
    minimumWidth: Design.rescueWindowMinimumWidth
    minimumHeight: Design.rescueWindowMinimumHeight + Design.appTitleBarHeight
    title: "SinpoSmart - 行車紀錄器"
    color: Design.transparent
    flags: Qt.Window | Qt.FramelessWindowHint
    modality: Qt.NonModal
    readonly property bool usesCustomTitleBar: true
    readonly property bool interactionsLocked: rescueVideoWindow.controller.isRunning
                                               || rescueVideoWindow.controller.isAwaitingConfirmation

    function positionBesideHost() {
        if (!rescueVideoWindow.screen)
            return
        const screenInfo = rescueVideoWindow.screen
        const availableX = screenInfo.virtualX
        const availableY = screenInfo.virtualY
        const availableWidth = screenInfo.desktopAvailableWidth
        const availableHeight = screenInfo.desktopAvailableHeight
        const margin = 16
        const rightX = hostWindow.x + hostWindow.width + margin
        const rightEdge = availableX + availableWidth
        const bottomEdge = availableY + availableHeight
        const maximumWidth = Math.max(1, availableWidth - margin * 2)
        rescueVideoWindow.width = Math.min(Design.rescueWindowWidth, maximumWidth)
        const centeredX = availableX + Math.round((availableWidth - rescueVideoWindow.width) / 2)
        rescueVideoWindow.x = rightX + rescueVideoWindow.width <= rightEdge - margin
                ? rightX
                : Math.max(availableX + margin, Math.min(centeredX, rightEdge - rescueVideoWindow.width - margin))
        rescueVideoWindow.y = Math.max(
                    availableY + margin,
                    Math.min(hostWindow.y, bottomEdge - rescueVideoWindow.height - margin))
    }

    function open() {
        const needsPositioning = !visible
        show()
        if (needsPositioning)
            positionBesideHost()
        raise()
        requestActivate()
    }

    onVisibleChanged: {
        if (visible && nativeTitleBarConfigurator && !usesCustomTitleBar)
            nativeTitleBarConfigurator()
    }

    onClosing: function(close) {
        if (rescueVideoWindow.interactionsLocked)
            close.accepted = false
    }

    Connections {
        target: rescueVideoWindow.controller

        function onDeleteConfirmationRequested() {
            rescueVideoDeleteConfirmation.open()
        }

        function onErrorOccurred(message) {
            rescueVideoWindow.errorHandler(message)
        }
    }

    FolderDialog {
        id: rescueVideoSourceDialog
        title: "選擇記憶卡 DCIM\\100CAREC 資料夾"
        onAccepted: rescueVideoWindow.controller.updateInputs(
            rescueVideoWindow.controller.localPath(selectedFolder),
            rescueVideoDateField.text,
            rescueVideoVehicleCombo.currentText
        )
    }

    AppleCalendarButton {
        id: rescueVideoDateCalendar
        objectName: "rescueVideoDateCalendarButton"
        triggerOnly: true
        anchorItem: rescueVideoDateField
        popupParent: rescueVideoWindow.contentItem
        dateText: rescueVideoDateField.text
        dateFormat: "iso"
        enabled: !rescueVideoWindow.controller.isRunning
                 && !rescueVideoWindow.controller.isAwaitingConfirmation
        onDateSelected: function(value) {
            rescueVideoDateField.text = value
            rescueVideoWindow.controller.refreshVehicleOptions(
                rescueVideoWindow.controller.sourcePath,
                value
            )
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: Design.radiusSheet
        color: Design.background
        border.width: Design.borderWidth
        border.color: Design.border
        z: -1
    }

    Rectangle {
        id: rescueVideoTitleBar
        objectName: "rescueVideoTitleBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Design.appTitleBarHeight
        color: Design.transparent
        z: 2

        Label {
            id: rescueVideoWindowTitleLabel
            objectName: "rescueVideoWindowTitleLabel"
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: "SinpoSmart - 行車紀錄器"
            color: Design.infoText
            font.pixelSize: Design.controlSize
            font.bold: true
        }

        Item {
            anchors.right: parent.right
            anchors.rightMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            width: Design.appWindowControlWidth * 3
            height: parent.height

            AppleButton {
                objectName: "rescueVideoTitleMinimizeButton"
                x: 0
                width: Design.appWindowControlWidth
                height: parent.height
                implicitWidth: Design.appWindowControlWidth
                implicitHeight: Design.appTitleBarHeight
                leftPadding: 0
                rightPadding: 0
                text: ""
                iconKind: "minimize"
                tone: "windowControl"
                font.pixelSize: Design.appWindowControlIconSize
                font.weight: Font.Normal
                instantFeedback: true
                showFocusRing: false
                focusPolicy: Qt.NoFocus
                scale: 1
                enabled: !rescueVideoWindow.interactionsLocked
                Accessible.name: "縮小行車紀錄器"
                onClicked: rescueVideoWindow.showMinimized()
            }

            AppleButton {
                objectName: "rescueVideoTitleMaximizeButton"
                x: Design.appWindowControlWidth
                width: Design.appWindowControlWidth
                height: parent.height
                implicitWidth: Design.appWindowControlWidth
                implicitHeight: Design.appTitleBarHeight
                leftPadding: 0
                rightPadding: 0
                text: ""
                iconKind: "maximize"
                iconToggled: rescueVideoWindow.visibility === Window.Maximized
                tone: "windowControl"
                font.pixelSize: Design.appWindowControlIconSize
                font.weight: Font.Normal
                instantFeedback: true
                showFocusRing: false
                focusPolicy: Qt.NoFocus
                scale: 1
                enabled: !rescueVideoWindow.interactionsLocked
                Accessible.name: rescueVideoWindow.visibility === Window.Maximized ? "還原行車紀錄器" : "最大化行車紀錄器"
                onClicked: {
                    if (rescueVideoWindow.visibility === Window.Maximized)
                        rescueVideoWindow.showNormal()
                    else
                        rescueVideoWindow.showMaximized()
                }
            }

            AppleButton {
                objectName: "rescueVideoTitleCloseButton"
                x: Design.appWindowControlWidth * 2
                width: Design.appWindowControlWidth
                height: parent.height
                implicitWidth: Design.appWindowControlWidth
                implicitHeight: Design.appTitleBarHeight
                leftPadding: 0
                rightPadding: 0
                text: ""
                iconKind: "close"
                tone: "windowClose"
                font.pixelSize: Design.appWindowControlIconSize
                font.weight: Font.Normal
                instantFeedback: true
                showFocusRing: false
                focusPolicy: Qt.NoFocus
                scale: 1
                enabled: !rescueVideoWindow.interactionsLocked
                Accessible.name: "關閉行車紀錄器"
                onClicked: rescueVideoWindow.close()
            }
        }

        DragHandler {
            target: null
            enabled: rescueVideoWindow.visibility !== Window.Maximized
                     && !rescueVideoWindow.interactionsLocked
            onActiveChanged: {
                if (active)
                    rescueVideoWindow.startSystemMove()
            }
        }
    }

    MouseArea {
        anchors.left: parent.left
        anchors.top: rescueVideoTitleBar.bottom
        anchors.bottom: parent.bottom
        width: Design.appResizeHandleWidth
        enabled: rescueVideoWindow.visibility !== Window.Maximized
                 && !rescueVideoWindow.interactionsLocked
        cursorShape: Qt.SizeHorCursor
        z: 3
        onPressed: rescueVideoWindow.startSystemResize(Qt.LeftEdge)
    }

    MouseArea {
        anchors.right: parent.right
        anchors.top: rescueVideoTitleBar.bottom
        anchors.bottom: parent.bottom
        width: Design.appResizeHandleWidth
        enabled: rescueVideoWindow.visibility !== Window.Maximized
                 && !rescueVideoWindow.interactionsLocked
        cursorShape: Qt.SizeHorCursor
        z: 3
        onPressed: rescueVideoWindow.startSystemResize(Qt.RightEdge)
    }

    MouseArea {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Design.appResizeHandleWidth
        enabled: rescueVideoWindow.visibility !== Window.Maximized
                 && !rescueVideoWindow.interactionsLocked
        cursorShape: Qt.SizeVerCursor
        z: 3
        onPressed: rescueVideoWindow.startSystemResize(Qt.BottomEdge)
    }

    ColumnLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: rescueVideoTitleBar.bottom
        anchors.bottom: parent.bottom
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Design.rescueHeaderHeight
            color: Design.strongHeader

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                StrongHeaderTitle {
                    objectName: "rescueVideoTitleLabel"
                    text: "救護行車影片分類"
                }
                Label {
                    objectName: "rescueVideoStatusBadge"
                    text: "● " + rescueVideoWindow.controller.statusText
                    color: Design.strongHeaderStatus
                    font.pixelSize: Design.bodySize
                    font.bold: true
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            Layout.topMargin: 16
            Layout.bottomMargin: 14
            spacing: 8

            ToolFormCard {
                Layout.fillWidth: true
                contentItem: RowLayout {
                    spacing: 8
                    FormFieldTitle { text: "日期" }
                    AppleTextField {
                        id: rescueVideoDateField
                        objectName: "rescueVideoDateField"
                        Layout.preferredWidth: Design.rescueDateWidth
                        text: rescueVideoWindow.controller.targetDate
                        enabled: !rescueVideoWindow.controller.isRunning
                                 && !rescueVideoWindow.controller.isAwaitingConfirmation
                        onEditingFinished: rescueVideoWindow.controller.refreshVehicleOptions(
                            rescueVideoWindow.controller.sourcePath,
                            text
                        )
                        clickAction: function() {
                            rescueVideoDateCalendar.openForCurrentDate()
                        }
                    }
                    FormFieldTitle { text: "車號" }
                    AppleComboBox {
                        id: rescueVideoVehicleCombo
                        objectName: "rescueVideoVehicleCombo"
                        Layout.preferredWidth: Design.rescueVehicleWidth
                        model: rescueVideoWindow.controller.vehicleOptions
                        currentIndex: model.indexOf(rescueVideoWindow.controller.selectedVehicle)
                        enabled: model.length > 0
                                 && !rescueVideoWindow.controller.isRunning
                                 && !rescueVideoWindow.controller.isAwaitingConfirmation
                        onActivated: rescueVideoWindow.controller.updateInputs(
                            rescueVideoWindow.controller.sourcePath,
                            rescueVideoDateField.text,
                            currentText
                        )
                    }
                    AppleButton {
                        objectName: "rescueVideoCheckButton"
                        text: "檢查及預覽分類"
                        tone: "neutralStrong"
                        enabled: !rescueVideoWindow.controller.isRunning
                                 && !rescueVideoWindow.controller.isAwaitingConfirmation
                        onClicked: rescueVideoWindow.controller.checkAndPreview(
                            rescueVideoWindow.controller.sourcePath,
                            rescueVideoDateField.text,
                            rescueVideoVehicleCombo.currentText
                        )
                    }
                    Label {
                        objectName: "rescueVideoSummaryText"
                        Layout.fillWidth: true
                        text: rescueVideoWindow.controller.summaryText
                        color: Design.secondaryText
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                }
            }

            ToolFormCard {
                Layout.fillWidth: true
                contentItem: ColumnLayout {
                    spacing: 8

                    DataSectionTitle {
                        text: "檢查結果"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Repeater {
                            model: rescueVideoWindow.controller.checkCards

                            delegate: Frame {
                                id: rescueVideoCheckCard
                                required property var modelData
                                objectName: "rescueVideoCheckCard_" + rescueVideoCheckCard.modelData.key
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Layout.minimumWidth: 0
                                implicitHeight: 138
                                padding: 10

                                background: Rectangle {
                                    radius: Design.radiusMedium
                                    color: Design.panel
                                    border.width: Design.borderWidth
                                    border.color: rescueVideoCheckCard.modelData.level === "ok"
                                                  ? Design.successBorder
                                                  : Design.dangerBorder
                                }

                                contentItem: ColumnLayout {
                                    spacing: 6

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6

                                        Rectangle {
                                            Layout.preferredWidth: 3
                                            Layout.preferredHeight: 18
                                            radius: Design.rescueCheckMarkerRadius
                                            color: rescueVideoCheckCard.modelData.level === "ok"
                                                   ? Design.successAction
                                                   : Design.dangerFill
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: rescueVideoCheckCard.modelData.title
                                            color: Design.text
                                            font.pixelSize: Design.bodySize
                                            font.bold: true
                                            elide: Text.ElideRight
                                        }
                                    }

                                    Label {
                                        text: rescueVideoCheckCard.modelData.level === "ok" ? "可用" : "需處理"
                                        color: rescueVideoCheckCard.modelData.level === "ok"
                                               ? Design.successText
                                               : Design.dangerStrong
                                        font.pixelSize: Design.captionSize
                                        font.bold: true
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        text: rescueVideoCheckCard.modelData.detail
                                        color: Design.secondaryText
                                        font.pixelSize: Design.captionSize
                                        wrapMode: Text.Wrap
                                        maximumLineCount: 3
                                        elide: Text.ElideRight
                                        verticalAlignment: Text.AlignTop
                                    }

                                    AppleButton {
                                        visible: rescueVideoCheckCard.modelData.key === "source"
                                                 && rescueVideoWindow.controller.sourcePath.length === 0
                                        Layout.fillWidth: true
                                        implicitHeight: Design.toolBrowseButtonHeight
                                        text: "選擇資料夾"
                                        tone: "neutralStrong"
                                        enabled: !rescueVideoWindow.controller.isRunning
                                                 && !rescueVideoWindow.controller.isAwaitingConfirmation
                                        onClicked: rescueVideoSourceDialog.open()
                                    }
                                }
                            }
                        }
                    }
                }
            }

            ToolFormCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentItem: ColumnLayout {
                    spacing: 0
                    DataSectionTitle {
                        objectName: "rescueVideoResultTitle"
                        text: "分類結果"
                        Layout.bottomMargin: 6
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Design.toolSmallButtonHeight
                        color: Design.softAction
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: 8
                            DataTableCell { column: "source"; heading: true; text: "來源檔案" }
                            DataTableCell { column: "time"; heading: true; text: "矯正影片時間" }
                            DataTableCell { column: "case"; heading: true; text: "案件資料夾" }
                            DataTableCell { column: "status"; heading: true; text: "狀態" }
                            DataTableCell { column: "transfer"; heading: true; text: "傳輸進度" }
                            DataTableCell { column: "destination"; heading: true; text: "目的地" }
                            DataTableCell { column: "note"; heading: true; text: "備註" }
                        }
                    }
                    ListView {
                        id: rescueVideoResultList
                        objectName: "rescueVideoResultList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: rescueVideoWindow.controller.resultModel

                        delegate: Rectangle {
                            id: rescueVideoResultRow
                            required property string sourceText
                            required property string timeText
                            required property string caseText
                            required property string statusText
                            required property string destinationText
                            required property string noteText
                            required property string tone
                            required property int transferPercent
                            required property string transferText
                            width: rescueVideoResultList.width
                            height: Design.rescueResultRowHeight
                            color: Design.panel
                            border.width: Design.borderWidth
                            border.color: Design.divider
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 8
                                DataTableCell { column: "source"; text: rescueVideoResultRow.sourceText }
                                DataTableCell { column: "time"; text: rescueVideoResultRow.timeText }
                                DataTableCell { column: "case"; text: rescueVideoResultRow.caseText }
                                DataTableCell {
                                    column: "status"
                                    text: rescueVideoResultRow.statusText
                                    tone: rescueVideoResultRow.tone
                                }
                                Item {
                                    Layout.preferredWidth: Design.dataTransferWidth
                                    Layout.preferredHeight: 22

                                    Rectangle {
                                        anchors.fill: parent
                                        radius: height / 2
                                        color: Design.softAction
                                        border.width: Design.borderWidth
                                        border.color: Design.divider
                                    }
                                    Rectangle {
                                        width: parent.width * rescueVideoResultRow.transferPercent / 100
                                        height: parent.height
                                        radius: height / 2
                                        color: rescueVideoResultRow.transferText === "傳輸失敗"
                                               ? Design.dangerFill
                                               : rescueVideoResultRow.transferPercent === 100
                                                 ? Design.successAction
                                                 : Design.blue
                                    }
                                    Label {
                                        anchors.fill: parent
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                        text: rescueVideoResultRow.transferText
                                              + " " + rescueVideoResultRow.transferPercent + "%"
                                        color: Design.text
                                        font.pixelSize: Design.captionSize
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }
                                }
                                DataTableCell {
                                    column: "destination"
                                    text: rescueVideoResultRow.destinationText
                                }
                                DataTableCell { column: "note"; text: rescueVideoResultRow.noteText }
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                AppleButton {
                    objectName: "rescueVideoCopyStartButton"
                    text: "複製啟動"
                    tone: "primary"
                    emphasizedBorder: true
                    enabled: rescueVideoWindow.controller.isReady
                             && rescueVideoWindow.controller.hasPreview
                             && !rescueVideoWindow.controller.isRunning
                             && !rescueVideoWindow.controller.isAwaitingConfirmation
                    onClicked: rescueVideoWindow.controller.prepareDelete(
                        rescueVideoWindow.controller.sourcePath,
                        rescueVideoWindow.controller.destinationPath,
                        rescueVideoDateField.text,
                        rescueVideoVehicleCombo.currentText,
                        rescueVideoWindow.controller.offsetText,
                        false
                    )
                }
                BusyIndicator {
                    running: rescueVideoWindow.controller.isRunning
                    visible: running
                }
                Item { Layout.fillWidth: true }
                AppleButton {
                    objectName: "rescueVideoCloseButton"
                    text: "關閉"
                    tone: "neutralStrong"
                    enabled: !rescueVideoWindow.interactionsLocked
                    onClicked: rescueVideoWindow.close()
                }
            }
        }
    }

    AppleDialog {
        id: rescueVideoDeleteConfirmation
        objectName: "rescueVideoDeleteConfirmation"
        anchors.centerIn: parent
        width: Math.min(rescueVideoWindow.width - 72, 500)
        modal: true
        title: "即將開始複製記憶卡至行車記錄器資料夾"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "確定"
        rejectText: "取消"
        acceptTone: "dangerFilled"
        onAccepted: rescueVideoWindow.controller.confirmDelete()
        onRejected: rescueVideoWindow.controller.cancelDelete()

        Label {
            width: parent.width
            text: rescueVideoWindow.controller.confirmationSummary
            color: Design.text
            wrapMode: Text.Wrap
        }
    }
}
