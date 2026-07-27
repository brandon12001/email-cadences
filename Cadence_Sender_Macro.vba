' =====================================================================
' CADENCE MERGE SENDER - Word VBA macro
' Reads the cadence CSV and sends one Outlook email per row with:
'   - Salesforce BCC
'   - Outlook HTML signature preserved
'   - A human-speed delay between messages
' =====================================================================

Option Explicit

Const SF_BCC As String = "emailtosalesforce@t-1ax8ubejepn0zmtae31rc9l6jpxtcqtrw5i3hnoyhx446efyxg.1r-gheeea2.gbr88.le.salesforce.com"
Const SEND_DELAY_SECONDS As Long = 15

Sub SendCadenceBatch()
    Dim fd As FileDialog
    Dim csvPath As String
    Dim fileNum As Integer
    Dim lineText As String
    Dim headers() As String
    Dim fields() As String
    Dim colEmail As Long, colSubject As Long, colBody As Long
    Dim olApp As Object, olMail As Object
    Dim inspector As Object, editor As Object, insertRange As Object
    Dim sent As Long, failed As Long, rowNum As Long, totalRows As Long
    Dim bodyText As String, errorSummary As String
    Dim i As Long

    Set fd = Application.FileDialog(msoFileDialogFilePicker)
    fd.Title = "Pick today's cadence merge CSV"
    fd.Filters.Clear
    fd.Filters.Add "CSV files", "*.csv"
    If fd.Show <> -1 Then Exit Sub
    csvPath = fd.SelectedItems(1)

    On Error Resume Next
    Set olApp = GetObject(, "Outlook.Application")
    If olApp Is Nothing Then Set olApp = CreateObject("Outlook.Application")
    On Error GoTo 0

    If olApp Is Nothing Then
        MsgBox "Could not start Outlook. Open Outlook first, then run again.", vbCritical
        Exit Sub
    End If

    fileNum = FreeFile
    Open csvPath For Input As #fileNum

    If EOF(fileNum) Then
        Close #fileNum
        MsgBox "The selected CSV is empty.", vbCritical
        Exit Sub
    End If

    Line Input #fileNum, lineText
    lineText = StripUtf8Bom(lineText)
    headers = ParseCsvLine(lineText)

    colEmail = -1
    colSubject = -1
    colBody = -1

    For i = LBound(headers) To UBound(headers)
        Select Case LCase$(Trim$(headers(i)))
            Case "email": colEmail = i
            Case "subject": colSubject = i
            Case "body": colBody = i
        End Select
    Next i

    If colEmail = -1 Or colSubject = -1 Or colBody = -1 Then
        Close #fileNum
        MsgBox "CSV must contain email, subject and body columns.", vbCritical
        Exit Sub
    End If

    Do While Not EOF(fileNum)
        Line Input #fileNum, lineText
        If Len(Trim$(lineText)) > 0 Then totalRows = totalRows + 1
    Loop
    Close #fileNum

    If totalRows = 0 Then
        MsgBox "The selected CSV has no email rows.", vbInformation
        Exit Sub
    End If

    If MsgBox("Send " & totalRows & " emails with BCC to Salesforce?" & vbCrLf & _
              "There will be a " & SEND_DELAY_SECONDS & " second gap between messages.", _
              vbYesNo + vbQuestion, "Cadence Sender") <> vbYes Then Exit Sub

    fileNum = FreeFile
    Open csvPath For Input As #fileNum
    Line Input #fileNum, lineText

    Do While Not EOF(fileNum)
        Line Input #fileNum, lineText
        If Len(Trim$(lineText)) = 0 Then GoTo NextRow

        rowNum = rowNum + 1
        fields = ParseCsvLine(lineText)

        If UBound(fields) < colBody Then
            failed = failed + 1
            errorSummary = errorSummary & "Row " & rowNum & ": incomplete CSV row" & vbCrLf
            GoTo NextRow
        End If

        If Len(Trim$(fields(colEmail))) = 0 Then
            failed = failed + 1
            errorSummary = errorSummary & "Row " & rowNum & ": blank email address" & vbCrLf
            GoTo NextRow
        End If

        On Error Resume Next
        Err.Clear

        Set olMail = olApp.CreateItem(0)
        With olMail
            .To = Trim$(fields(colEmail))
            .BCC = SF_BCC
            .Subject = fields(colSubject)
            .Display
            DoEvents

            bodyText = Replace(fields(colBody), "\n", vbCrLf)

            Set inspector = .GetInspector
            Set editor = inspector.WordEditor
            Set insertRange = editor.Range(0, 0)
            insertRange.InsertBefore bodyText & vbCrLf & vbCrLf

            .Send
        End With

        If Err.Number = 0 Then
            sent = sent + 1
        Else
            failed = failed + 1
            errorSummary = errorSummary & "Row " & rowNum & " (" & _
                           Trim$(fields(colEmail)) & "): " & Err.Description & vbCrLf
            Err.Clear
        End If

        On Error GoTo 0
        Set insertRange = Nothing
        Set editor = Nothing
        Set inspector = Nothing
        Set olMail = Nothing

        If Not EOF(fileNum) Then WaitSeconds SEND_DELAY_SECONDS

NextRow:
    Loop

    Close #fileNum

    Dim resultMessage As String
    resultMessage = "Done. Sent " & sent & ", failed " & failed & "."

    If failed = 0 Then
        resultMessage = resultMessage & vbCrLf & vbCrLf & _
                        "Every row sent. You can now advance this batch in the app."
        MsgBox resultMessage, vbInformation, "Cadence Sender"
    Else
        resultMessage = resultMessage & vbCrLf & vbCrLf & _
                        "Do not advance the batch in the app because some rows failed." & _
                        vbCrLf & vbCrLf & Left$(errorSummary, 1800)
        MsgBox resultMessage, vbExclamation, "Cadence Sender"
    End If
End Sub

Private Function StripUtf8Bom(ByVal text As String) As String
    If Len(text) > 0 And Left$(text, 1) = ChrW(&HFEFF) Then
        text = Mid$(text, 2)
    End If

    If Left$(text, 3) = "ï»¿" Then
        text = Mid$(text, 4)
    End If

    StripUtf8Bom = text
End Function

Private Sub WaitSeconds(ByVal seconds As Long)
    Dim finishAt As Date
    finishAt = DateAdd("s", seconds, Now)
    Do While Now < finishAt
        DoEvents
    Loop
End Sub

Private Function ParseCsvLine(ByVal text As String) As String()
    Dim result() As String
    Dim buffer As String
    Dim inQuotes As Boolean
    Dim character As String
    Dim i As Long, fieldIndex As Long

    ReDim result(0 To 0)
    fieldIndex = 0

    For i = 1 To Len(text)
        character = Mid$(text, i, 1)

        If character = """" Then
            If inQuotes And i < Len(text) And Mid$(text, i + 1, 1) = """" Then
                buffer = buffer & """"
                i = i + 1
            Else
                inQuotes = Not inQuotes
            End If
        ElseIf character = "," And Not inQuotes Then
            ReDim Preserve result(0 To fieldIndex)
            result(fieldIndex) = buffer
            fieldIndex = fieldIndex + 1
            buffer = ""
        Else
            buffer = buffer & character
        End If
    Next i

    ReDim Preserve result(0 To fieldIndex)
    result(fieldIndex) = buffer
    ParseCsvLine = result
End Function
