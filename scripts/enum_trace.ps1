# Where does list enumeration break? Pull the GUI trace markers for the last
# failing /search out of logs\server.log. ASCII only in code; pattern strings use
# unicode escapes to keep this file ASCII.
$log = "D:\ConsPlus\logs\server.log"
$pat = "enumerate_titles start_abs|open_first_doc|goto_doc_index|next_doc|enumerate_titles:|doc idx=|position|pos="
Get-Content $log -Encoding UTF8 -Tail 4000 | Select-String -Pattern $pat |
    Select-Object -Last 60 | ForEach-Object { $_.Line }
