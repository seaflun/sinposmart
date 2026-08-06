import QtQuick
import "../styles"

Rectangle {
    required property bool dutyMode
    required property bool selectedState
    required property string tone
    height: dutyMode ? Design.dutyTaskRowHeight : Design.auditTaskRowHeight
    radius: Design.radiusSmall
    color: dutyMode ? Design.panel
         : selectedState ? Design.comboButton
         : tone === "triggered" ? Design.successDoneSurface
         : tone === "running" ? Design.comboHover
         : tone === "manual" ? Design.warningSurface
         : Design.panel
    border.color: dutyMode
                  ? (selectedState ? Design.blue : Design.taskBorder)
                  : (selectedState ? Design.blue : Design.border)
    border.width: selectedState ? Design.focusBorderWidth : Design.borderWidth
}
