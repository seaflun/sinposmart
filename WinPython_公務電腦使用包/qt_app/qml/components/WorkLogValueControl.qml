import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

RowLayout {
    id: workLogValue
    required property var settingsController
    required property string settingKey
    required property string labelText
    required property string unitText
    spacing: 3

    Label {
        text: workLogValue.labelText
        color: Design.secondaryText
        font.pixelSize: Design.captionSize
    }
    AppleTextField {
        objectName: workLogValue.settingKey + "Field"
        Layout.preferredWidth: Design.workLogValueFieldWidth
        Layout.preferredHeight: Design.workLogValueFieldHeight
        Accessible.name: workLogValue.labelText
        text: String(workLogValue.settingsController.values[workLogValue.settingKey] ?? 0)
        horizontalAlignment: TextInput.AlignHCenter
        validator: IntValidator { bottom: 0 }
        onTextEdited: {
            if (text.length > 0 && acceptableInput)
                workLogValue.settingsController.setValue(workLogValue.settingKey, text)
        }
        onEditingFinished: workLogValue.settingsController.setValue(
            workLogValue.settingKey,
            text
        )
    }
    Label {
        text: workLogValue.unitText
        color: Design.muted
        font.pixelSize: Design.captionSize
    }
}
