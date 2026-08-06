import QtQuick
import QtQuick.Controls
import "../styles"

Rectangle {
    objectName: "dutyTaskStatusPill"
    required property string tone
    required property string statusText
    implicitWidth: Design.taskStatusWidth
    implicitHeight: Design.taskStatusHeight
    radius: Design.radiusSheet
    color: tone === "running" ? Design.blue
         : tone === "triggered" ? Design.taskTriggeredSurface
         : tone === "manual" ? Design.warningSurface
         : Design.taskReadySurface

    Label {
        anchors.centerIn: parent
        text: parent.statusText
        color: parent.tone === "running" ? Design.panel
             : parent.tone === "triggered" ? Design.successText
             : parent.tone === "manual" ? Design.warningText
             : Design.taskReadyText
        font.bold: true
        font.pixelSize: Design.captionSize
    }
}
