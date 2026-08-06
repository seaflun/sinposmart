import QtQuick
import QtQuick.Controls
import "../styles"

Rectangle {
    id: summaryCard
    required property string summaryText
    required property string tone
    implicitHeight: 50
    radius: Design.radius
    color: tone === "todo" ? Design.todoSurface
         : tone === "review" ? Design.reviewSurface
         : tone === "ready" ? Design.comboHover
         : Design.successDoneSurface
    border.color: Design.summaryBorder

    Label {
        anchors.fill: parent
        anchors.margins: 8
        text: summaryCard.summaryText
        color: summaryCard.tone === "todo" ? Design.todoText
             : summaryCard.tone === "review" ? Design.reviewText
             : summaryCard.tone === "ready" ? Design.blueHover
             : Design.successText
        font.pixelSize: Design.windowTitleSize
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
