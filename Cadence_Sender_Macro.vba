' =====================================================================
' CADENCE MERGE SENDER - Word VBA macro
' Sends one email per row of the cadence merge CSV via Outlook, with:
'   - BCC to Salesforce on every message
'   - Your Outlook signature preserved
'   - A send delay between messages (human-speed, protects the domain)
'
' WHY THIS EXISTS: Word's built-in merge-to-email cannot BCC and skips
' signatures. This macro reads the CSV directly and sends real Outlook
' emails instead - both problems solved.
'
' =====================================================================
' ONE-TIME INSTALL (5 minutes)
' 1. Open Word (any blank document is fine - you do NOT need a merge
'    template anymore; the CSV already contains the finished emails).
' 2. Press Alt+F11 to open the VBA editor.
' 3. Insert menu -> Module. Paste ALL of this code into the module.
' 4. Tools -> References -> tick "Microsoft Outlook 16.0 Object Library"
'    -> OK. (If you skip this the code still works via late binding.)
' 5. Close the editor. Save the document as "Cadence Sender.docm"
'    (macro-enabled) somewhere handy. That doc is now your send button.
'
' DAILY USE
' 1. Download the merge CSV from the cadence app.
' 2. Open Cadence Sender.docm -> Alt+F8 -> run SendCadenceBatch.
' 3. Pick the CSV when prompted. It shows a count and confirms.
' 4. Watch it send. Then go back to the app and click
'    "I've sent this batch - advance all".
'
' SETTINGS - edit these two lines before first use:
' =====================================================================

Option Explicit

Const SF_BCC As String = "emailtosalesforce@t-1ax8ubejepn0zmtae31rc9l6jpxtcqtrw5i3hnoyhx446efyxg.1r-gheeea2.gbr88.le.salesforce.com"
Const SEND_DELAY_SECONDS As Long = 15   ' gap between sends - keep human-speed

Sub SendCadenceBatch()
    Dim fd As FileDialog
    Dim csvPath As String
    Dim fileNum As Integer
    Dim lineText As String
    Dim headers() As String
    Dim fields() As String
    Dim colEmail As Long, colSubject As Long, colBody As Long, colName As Long
    Dim olApp As Object, olMail As Object
    Dim sent As Long, failed As Long, rowNum As Long
    Dim i As Long

    ' --- pick the CSV ---
    Set fd = Application.FileDialog(msoFileDialogFilePicker)
    fd.Title = "Pick today's cadence merge CSV"
    fd.Filters.Clear
    fd.Filters.Add "CSV files", "*.csv"
    If fd.Show <> -1 Then Exit Sub
    csvPath = fd.SelectedItems(1)

    ' --- connect to Outlook ---
    On Error Resume Next
    Set olApp = GetObject(, "Outlook.Application")
    If olApp Is Nothing Then Set olApp = CreateObject("Outlook.Application")
    On Error GoTo 0
    If olApp Is Nothing Then
        MsgBox "Could not start Outlook. Open Outlook first, then run again.", vbCritical
        Exit Sub
    End If

    ' --- read the CSV ---
    fileNum = FreeFile
    Open csvPath For Input As #fileNum

    ' header row
    Line Input #fileNum, lineText
    headers = ParseCsvLine(lineText)
    colEmail = -1: colSubject = -1: colBody = -1: colName = -1
    For i = LBound(headers) To UBound(headers)
        Select Case LCase(Trim(headers(i)))
            Case "email":   colEmail = i
            Case "subject": colSubject = i
            Case "body":    colBody = i
            Case "name":    colName = i
        End Select
    Next i
    If colEmail = -1 Or colSubject = -1 Or colBody = -1 Then
        MsgBox "CSV must contain email, subject and body columns.", vbCritical
        Close #fileNum
        Exit Sub
    End If

    ' --- count rows first for the confirm dialog ---
    Dim totalRows As Long
    totalRows = 0
    Do While Not EOF(fileNum)
        Line Input #fileNum, lineText
        If Len(Trim(lineText)) > 0 Then totalRows = totalRows + 1
    Loop
    Close #fileNum

    If MsgBox("Send " & totalRows & " emails with BCC to Salesforce?" & vbCrLf & _
              "(" & SEND_DELAY_SECONDS & "s gap between each)", _
              vbYesNo + vbQuestion, "Cadence Sender") <> vbYes Then Exit Sub

    ' --- second pass: send ---
    fileNum = FreeFile
    Open csvPath For Input As #fileNum
    Line Input #fileNum, lineText   ' skip header
    rowNum = 0

    Do While Not EOF(fileNum)
        Line Input #fileNum, lineText
        If Len(Trim(lineText)) = 0 Then GoTo NextRow
        rowNum = rowNum + 1
        fields = ParseCsvLine(lineText)
        If UBound(fields) < colBody Then GoTo NextRow

        On Error Resume Next
        Set olMail = olApp.CreateItem(0)  ' olMailItem
        With olMail
            .To = Trim(fields(colEmail))
            .BCC = SF_BCC
            .Subject = fields(colSubject)
            ' .Display first so the default signature is inserted, then
            ' prepend the body above it.
            .Display
            Dim bodyText As String
            bodyText = Replace(fields(colBody), "\n", vbCrLf)
            .Body = bodyText & vbCrLf & vbCrLf & .Body
            .Send
        End With
        If Err.Number = 0 Then
            sent = sent + 1
        Else
            failed = failed + 1
            Err.Clear
        End If
        On Error GoTo 0
        Set olMail = Nothing

        ' human-speed gap
        Dim waitUntil As Double
        waitUntil = Timer + SEND_DELAY_SECONDS
        Do While Timer < waitUntil
            DoEvents
        Loop
NextRow:
    Loop
    Close #fileNum

    MsgBox "Done. Sent " & sent & ", failed " & failed & "." & vbCrLf & _
           "Now go to the cadence app and click 'I've sent this batch - advance all'.", _
           vbInformation, "Cadence Sender"
End Sub

' --- minimal CSV parser. The app writes email bodies on ONE line with
'     the token \n standing in for line breaks (converted back above), so
'     each CSV row is a single physical line. Handles quoted commas/quotes. ---
Private Function ParseCsvLine(ByVal s As String) As String()
    Dim result() As String
    Dim buf As String
    Dim inQuotes As Boolean
    Dim ch As String
    Dim i As Long, n As Long
    ReDim result(0 To 0)
    n = 0
    inQuotes = False
    For i = 1 To Len(s)
        ch = Mid(s, i, 1)
        If ch = """" Then
            If inQuotes And i < Len(s) And Mid(s, i + 1, 1) = """" Then
                buf = buf & """"
                i = i + 1
            Else
                inQuotes = Not inQuotes
            End If
        ElseIf ch = "," And Not inQuotes Then
            ReDim Preserve result(0 To n)
            result(n) = buf
            n = n + 1
            buf = ""
        Else
            buf = buf & ch
        End If
    Next i
    ReDim Preserve result(0 To n)
    result(n) = buf
    ParseCsvLine = result
End Function
