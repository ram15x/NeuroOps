# NeuroOps Project Cleanup Script
Write-Host "🧹 Cleaning NeuroOps Project..." -ForegroundColor Cyan

# 1. Remove Python cache
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Recurse -File -Filter "*.pyc" | Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host "  ✅ Python cache cleaned"

# 2. Remove backup files
Get-ChildItem -Path . -Recurse -File -Filter "*.backup" | Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host "  ✅ Backup files removed"

# 3. Remove old logs (older than 7 days)
Get-ChildItem -Path . -File -Filter "*.log" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host "  ✅ Old logs removed"

# 4. Remove empty directories
Get-ChildItem -Path . -Recurse -Directory | Where-Object { (Get-ChildItem $_.FullName -Force | Measure-Object).Count -eq 0 } | Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host "  ✅ Empty directories removed"

# 5. Remove garbage files
@("all_files.txt", "file_structure.txt", "folder_structure.txt", "neuroops_*.txt", "source", "vn mv*") | ForEach-Object {
    Get-ChildItem -Path . -File -Filter $_ | Remove-Item -Force -ErrorAction SilentlyContinue
}
Write-Host "  ✅ Garbage files removed"

Write-Host "`n✅ Cleanup complete!" -ForegroundColor Green
