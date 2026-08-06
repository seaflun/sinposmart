pragma ComponentBehavior: Bound

import QtQuick
import "../styles"

AppleButton {
    id: settingsButton
    implicitWidth: Design.settingsButtonSize
    implicitHeight: Design.settingsButtonSize
    tone: "ghost"

    contentItem: Item {
        Item {
            id: settingsIcon
            anchors.centerIn: parent
            width: Design.settingsIconSize
            height: Design.settingsIconSize

            Repeater {
                model: 8

                delegate: Rectangle {
                    id: settingsSpoke
                    required property int index
                    width: Design.settingsIconSpokeWidth
                    height: Design.settingsIconSpokeHeight
                    x: (settingsIcon.width - width) / 2
                    y: 0
                    radius: width / 2
                    color: settingsButton.enabled ? Design.controlText : Design.muted
                    transform: Rotation {
                        origin.x: settingsSpoke.width / 2
                        origin.y: Design.settingsIconSize / 2
                        angle: settingsSpoke.index * 45
                    }
                }
            }

            Rectangle {
                anchors.centerIn: parent
                width: Design.settingsIconRingSize
                height: Design.settingsIconRingSize
                radius: width / 2
                color: Design.transparent
                border.width: Design.settingsIconSpokeWidth
                border.color: settingsButton.enabled ? Design.controlText : Design.muted
            }
        }
    }
}
