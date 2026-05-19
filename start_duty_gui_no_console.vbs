Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = "pythonw.exe " & Chr(34) & fso.BuildPath(scriptDir, "duty_gui.pyw") & Chr(34)

shell.CurrentDirectory = scriptDir
shell.Run command, 0, False
