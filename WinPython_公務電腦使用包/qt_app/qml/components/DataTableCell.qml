import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

Label {
    property string column: ""
    property bool heading: false
    property string tone: ""
    readonly property int columnWidth: column === "source" ? Design.dataSourceWidth
                                       : column === "time" ? Design.dataTimeWidth
                                       : column === "case" ? Design.dataCaseWidth
                                       : column === "status" ? Design.dataStatusWidth
                                       : column === "transfer" ? Design.dataTransferWidth
                                       : column === "destination" ? Design.dataDestinationWidth
                                       : Design.dataNoteWidth
    Layout.preferredWidth: columnWidth
    Layout.fillWidth: column === "destination" || column === "note"
    color: heading ? Design.secondaryText
                   : tone === "ok" || tone === "deleted" ? Design.success
                   : tone === "warning" ? Design.warningStrong
                   : tone === "error" ? Design.dangerStrong
                   : Design.text
    font.pixelSize: heading ? Design.captionSize : Design.bodySize
    font.bold: heading || column === "status"
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
}
