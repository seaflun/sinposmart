import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

Control {
    id: toolStatusBar
    property alias text: statusLabel.text
    property bool dismissed: false
    property bool onlyShowErrors: false
    property bool errorState: false
    property bool compact: false
    signal detailsRequested(string message)
    readonly property string statusCategory: {
        const normalized = text.replace(/^\s*狀態\s*[：:]\s*/, "").trim()
        if (toolStatusBar.errorState || /(失敗|錯誤|error|中斷|找不到|未通過|異常|逾時|無法|不能|必須|請先|尚未完成|缺少|未能|不正確|原生.*遷移中|請由工具中心)/i.test(normalized))
            return "error"
        if (/(移除|刪除)/.test(normalized))
            return "warning"
        if (/^(準備就緒|尚未選擇)/.test(normalized))
            return "ready"
        if (/(完成|完畢|已填入|檢查通過|已送出|已新增)/.test(normalized))
            return "success"
        return "progress"
    }
    visible: !toolStatusBar.dismissed
             && (!toolStatusBar.onlyShowErrors || toolStatusBar.statusCategory === "error")
    Layout.fillWidth: true
    implicitHeight: toolStatusBar.compact ? 24 : Design.toolStatusHeight
    leftPadding: 12
    rightPadding: 12
    background: Rectangle {
        radius: Design.radiusMedium
        color: toolStatusBar.statusCategory === "error" ? Design.sideStatusErrorSurface
             : toolStatusBar.statusCategory === "warning" ? Design.sideStatusWarningSurface
             : toolStatusBar.statusCategory === "success" ? Design.sideStatusSuccessSurface
             : toolStatusBar.statusCategory === "progress" ? Design.sideStatusProgressSurface
             : Design.sideStatusReadySurface
        border.width: Design.borderWidth
        border.color: toolStatusBar.statusCategory === "error" ? Design.sideStatusErrorBorder
                    : toolStatusBar.statusCategory === "warning" ? Design.sideStatusWarningBorder
                    : toolStatusBar.statusCategory === "success" ? Design.sideStatusSuccessBorder
                    : toolStatusBar.statusCategory === "progress" ? Design.sideStatusProgressBorder
                    : Design.sideStatusReadyBorder
    }
    onTextChanged: toolStatusBar.dismissed = false

    contentItem: RowLayout {
        spacing: toolStatusBar.compact ? 4 : 6

        Label {
            id: statusLabel
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            color: toolStatusBar.statusCategory === "error" ? Design.sideStatusErrorText
                 : toolStatusBar.statusCategory === "warning" ? Design.sideStatusWarningText
                 : toolStatusBar.statusCategory === "success" ? Design.sideStatusSuccessText
                 : toolStatusBar.statusCategory === "progress" ? Design.sideStatusProgressText
                 : Design.sideStatusReadyText
            font.pixelSize: toolStatusBar.compact ? Design.captionSize : Design.bodySize
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
        }

        AppleButton {
            objectName: "toolStatusDetailsButton"
            visible: toolStatusBar.statusCategory === "error"
            implicitWidth: toolStatusBar.compact ? 72 : 76
            implicitHeight: toolStatusBar.compact ? 22 : 30
            text: "查看明細"
            tone: "danger"
            showFocusRing: true
            focusPolicy: Qt.TabFocus
            Accessible.name: "查看工具錯誤明細"
            onClicked: toolStatusBar.detailsRequested(statusLabel.text)
        }

        AppleButton {
            objectName: "toolStatusCloseButton"
            visible: toolStatusBar.statusCategory === "error"
            implicitWidth: toolStatusBar.compact ? 54 : 58
            implicitHeight: toolStatusBar.compact ? 22 : 30
            text: "關閉"
            tone: "danger"
            showFocusRing: true
            focusPolicy: Qt.TabFocus
            Accessible.name: "關閉工具錯誤"
            onClicked: toolStatusBar.dismissed = true
        }
    }
}
