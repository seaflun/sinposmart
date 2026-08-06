pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

AppleButton {
    id: calendarButton
    property string dateText: ""
    property string dateFormat: "slash"
    property var visibleDate: dateFromText(dateText)
    property Item anchorItem: null
    property Item popupParent: null
    property bool triggerOnly: false
    readonly property bool popupVisible: calendarPopup.visible
    signal dateSelected(string value)

    visible: !triggerOnly
    implicitWidth: triggerOnly ? 0 : Design.toolDateStepWidth
    implicitHeight: triggerOnly ? 0 : Design.toolDateStepHeight
    leftPadding: 0
    rightPadding: 0
    tone: "info"
    Accessible.name: "開啟月曆"

    function dateFromText(value) {
        const source = String(value || "").trim()
        if (dateFormat === "roc") {
            const digits = source.replace(/\D/g, "")
            if (digits.length === 7)
                return new Date(Number(digits.slice(0, 3)) + 1911, Number(digits.slice(3, 5)) - 1, Number(digits.slice(5, 7)))
        }
        const match = source.match(/^(\d{4})[-\/](\d{2})[-\/](\d{2})$/)
        if (match)
            return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
        return new Date()
    }

    function formattedDate(value) {
        const year = value.getFullYear()
        const month = String(value.getMonth() + 1).padStart(2, "0")
        const day = String(value.getDate()).padStart(2, "0")
        if (dateFormat === "roc")
            return String(year - 1911).padStart(3, "0") + month + day
        return dateFormat === "iso" ? year + "-" + month + "-" + day : year + "/" + month + "/" + day
    }

    function selectDate(value) {
        visibleDate = value
        dateSelected(formattedDate(value))
        calendarPopup.close()
    }

    function shiftMonth(months) {
        visibleDate = new Date(visibleDate.getFullYear(), visibleDate.getMonth() + months, 1)
    }

    function isSelected(value) {
        const selected = dateFromText(dateText)
        return value.getFullYear() === selected.getFullYear()
                && value.getMonth() === selected.getMonth()
                && value.getDate() === selected.getDate()
    }

    onDateTextChanged: {
        if (!calendarPopup.visible)
            visibleDate = dateFromText(dateText)
    }

    function openForCurrentDate() {
        visibleDate = dateFromText(dateText)
        calendarPopup.open()
    }

    function closeCalendar() {
        calendarPopup.close()
    }

    onClicked: openForCurrentDate()

    contentItem: Item {
        Rectangle {
            anchors.centerIn: parent
            width: 15
            height: 14
            radius: Design.radiusSmall
            color: Design.transparent
            border.width: Design.borderWidth
            border.color: calendarButton.enabled ? Design.blueHover : Design.muted
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.verticalCenter
            anchors.topMargin: -4
            width: 13
            height: Design.borderWidth
            color: calendarButton.enabled ? Design.blueHover : Design.muted
        }
        Repeater {
            model: 2

            delegate: Rectangle {
                required property int index
                anchors.top: parent.verticalCenter
                anchors.topMargin: -9
                x: parent.width / 2 + (index === 0 ? -5 : 3)
                width: 2
                height: 4
                radius: width / 2
                color: calendarButton.enabled ? Design.blueHover : Design.muted
            }
        }
    }

    Popup {
        id: calendarPopup
        parent: calendarButton.popupParent || calendarButton
        x: {
            const target = calendarButton.anchorItem || calendarButton
            const host = calendarPopup.parent
            if (!target || !host)
                return 0
            const point = target.mapToItem(host, target.width - width, target.height + 6)
            return Math.max(8, Math.min(point.x, host.width - width - 8))
        }
        y: {
            const target = calendarButton.anchorItem || calendarButton
            const host = calendarPopup.parent
            if (!target || !host)
                return 0
            const below = target.mapToItem(host, 0, target.height + 6).y
            if (below + height <= host.height - 8)
                return below
            return Math.max(8, target.mapToItem(host, 0, -height - 6).y)
        }
        z: 1000
        width: Design.calendarPopupWidth
        padding: 10
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: Design.radiusMedium
            color: Design.panel
            border.width: Design.borderWidth
            border.color: Design.border
        }

        contentItem: ColumnLayout {
            spacing: 8

            RowLayout {
                Layout.fillWidth: true

                AppleButton {
                    implicitWidth: Design.toolDateStepWidth
                    implicitHeight: Design.toolDateStepHeight
                    leftPadding: 0
                    rightPadding: 0
                    text: "<"
                    tone: "info"
                    Accessible.name: "上一個月"
                    onClicked: calendarButton.shiftMonth(-1)
                }
                Label {
                    Layout.fillWidth: true
                    text: (calendarButton.dateFormat === "roc" ? "民國 " + (calendarButton.visibleDate.getFullYear() - 1911) : calendarButton.visibleDate.getFullYear())
                          + " 年 " + (calendarButton.visibleDate.getMonth() + 1) + " 月"
                    color: Design.infoText
                    font.pixelSize: Design.controlSize
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                }
                AppleButton {
                    implicitWidth: Design.toolDateStepWidth
                    implicitHeight: Design.toolDateStepHeight
                    leftPadding: 0
                    rightPadding: 0
                    text: ">"
                    tone: "info"
                    Accessible.name: "下一個月"
                    onClicked: calendarButton.shiftMonth(1)
                }
            }

            DayOfWeekRow {
                id: weekdayRow
                Layout.fillWidth: true
                locale: Qt.locale("zh_TW")
                spacing: 4
                font.pixelSize: Design.captionSize

                delegate: Label {
                    required property string shortName
                    width: (weekdayRow.width - weekdayRow.spacing * 6) / 7
                    text: shortName
                    color: Design.secondaryText
                    font: weekdayRow.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            MonthGrid {
                id: monthGrid
                Layout.fillWidth: true
                Layout.preferredHeight: Design.calendarDayHeight * 6 + spacing * 5
                year: calendarButton.visibleDate.getFullYear()
                month: calendarButton.visibleDate.getMonth()
                locale: Qt.locale("zh_TW")
                spacing: 4
                font.pixelSize: Design.bodySize

                delegate: Item {
                    id: calendarDay
                    required property var model
                    property bool inDisplayedMonth: model.month === monthGrid.month
                    property date calendarDate: new Date(monthGrid.year, monthGrid.month, model.day)
                    property bool selected: inDisplayedMonth && calendarButton.isSelected(calendarDate)
                    implicitWidth: (monthGrid.width - monthGrid.spacing * 6) / 7
                    implicitHeight: Design.calendarDayHeight
                    opacity: inDisplayedMonth ? 1 : 0

                    Rectangle {
                        anchors.centerIn: parent
                        width: Design.calendarDayHeight
                        height: Design.calendarDayHeight
                        radius: width / 2
                        color: parent.selected ? Design.blue
                             : calendarDayMouseArea.containsMouse ? Design.comboHover
                             : Design.transparent
                    }
                    Label {
                        anchors.fill: parent
                        text: calendarDay.model.day
                        color: parent.selected ? Design.panel : Design.text
                        font.pixelSize: Design.bodySize
                        font.bold: parent.selected
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    MouseArea {
                        id: calendarDayMouseArea
                        anchors.fill: parent
                        enabled: parent.inDisplayedMonth
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: calendarButton.selectDate(calendarDay.calendarDate)
                    }
                }
            }
        }
    }
}
