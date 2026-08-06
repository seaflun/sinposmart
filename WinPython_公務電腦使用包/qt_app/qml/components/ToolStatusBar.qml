import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

Control {
    id: toolStatusBar
    property alias text: statusLabel.text
    readonly property string statusCategory: {
        const normalized = text.replace(/^\s*狀態\s*[：:]\s*/, "").trim()
        if (/(失敗|錯誤|中斷|找不到|未通過|異常|逾時)/.test(normalized))
            return "error"
        if (/(移除|刪除)/.test(normalized))
            return "warning"
        if (/^(準備就緒|尚未選擇)/.test(normalized))
            return "ready"
        if (/(完成|完畢|已填入|檢查通過|已送出|已新增)/.test(normalized))
            return "success"
        return "progress"
    }
    Layout.fillWidth: true
    implicitHeight: Design.toolStatusHeight
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
    contentItem: Label {
        id: statusLabel
        color: toolStatusBar.statusCategory === "error" ? Design.sideStatusErrorText
             : toolStatusBar.statusCategory === "warning" ? Design.sideStatusWarningText
             : toolStatusBar.statusCategory === "success" ? Design.sideStatusSuccessText
             : toolStatusBar.statusCategory === "progress" ? Design.sideStatusProgressText
             : Design.sideStatusReadyText
        font.pixelSize: Design.bodySize
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.Wrap
    }
}
