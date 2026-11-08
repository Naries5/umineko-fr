using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace UminekoFR;

public sealed class RemoteManifest
{
    public int SchemaVersion { get; set; } = 1;
    public string Version { get; set; } = "";

    // Legacy updater compatibility. Keep these fields in manifest.json
    // while users of the old wrapper still exist.
    public string? DownloadUrl { get; set; }
    public string? Sha256 { get; set; }

    public string? Notes { get; set; }
    public bool Requires07thMod { get; set; } = true;
    public List<RemotePackage>? Packages { get; set; }
    public List<RemoteFile>? Files { get; set; }
    public List<string>? DeletePaths { get; set; }
    public RemoteUpdater? Updater { get; set; }
}

public sealed class RemoteUpdater
{
    public string Version { get; set; } = "";
    public string DownloadUrl { get; set; } = "";
    public string Sha256 { get; set; } = "";
    public long Size { get; set; }
}

public sealed class RemotePackage
{
    public string Id { get; set; } = "";
    public string DownloadUrl { get; set; } = "";
    public string Sha256 { get; set; } = "";
    public long Size { get; set; }
}

public sealed class RemoteFile
{
    public string Path { get; set; } = "";
    public string Sha256 { get; set; } = "";
    public string PackageId { get; set; } = "";
    public long Size { get; set; }
}

public sealed record UpdaterConfig(
    string ManifestUrl,
    int TimeoutSeconds = 20,
    bool LaunchIfUpdateFails = true
);

public sealed record BackupEntry(
    string RelativePath,
    bool ExistedBefore
);

public sealed class LocalPatchState
{
    public string Version { get; set; } = "0";
    public Dictionary<string, string> Files { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);
}

public sealed record SeventhModDetection(
    bool Installed,
    string Reason
);

public static class UpdaterCore
{
    public const string ConfigFile = "umineko_fr_updater.json";
    public const string LocalVersionFile = "umineko_fr_version.txt";
    public const string LocalStateFile = "umineko_fr_state.json";
    public const string BackupDirName = ".umineko_fr_backup";
    public const string BackupManifestFile = "backup_manifest.json";

    public static async Task<RemoteManifest> GetRemoteManifestAsync(
        string manifestUrl,
        int timeoutSeconds = 20)
    {
        using var http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(Math.Max(5, timeoutSeconds))
        };
        http.DefaultRequestHeaders.UserAgent.ParseAdd(
            "Le-Sanglot-des-Goelands-Updater/3.0"
        );

        string json = await http.GetStringAsync(manifestUrl);
        var manifest = JsonSerializer.Deserialize<RemoteManifest>(
            json,
            JsonOptions()
        );

        if (manifest is null || string.IsNullOrWhiteSpace(manifest.Version))
            throw new Exception("Le manifeste distant est invalide.");

        bool hasFileManifest = manifest.Files is { Count: > 0 };
        if (hasFileManifest)
        {
            if (manifest.Packages is not { Count: > 0 })
                throw new Exception("Le manifeste v2 ne contient aucun package.");

            var packageIds = new HashSet<string>(
                manifest.Packages.Select(p => p.Id),
                StringComparer.OrdinalIgnoreCase
            );

            foreach (var package in manifest.Packages)
            {
                if (string.IsNullOrWhiteSpace(package.Id) ||
                    string.IsNullOrWhiteSpace(package.DownloadUrl) ||
                    string.IsNullOrWhiteSpace(package.Sha256))
                    throw new Exception("Un package du manifeste est invalide.");
            }

            foreach (var file in manifest.Files)
            {
                ValidateRelativePath(file.Path);
                if (string.IsNullOrWhiteSpace(file.Sha256) ||
                    string.IsNullOrWhiteSpace(file.PackageId) ||
                    !packageIds.Contains(file.PackageId))
                    throw new Exception(
                        $"Entrée de fichier invalide dans le manifeste : {file.Path}"
                    );
            }
        }
        else if (string.IsNullOrWhiteSpace(manifest.DownloadUrl) ||
                 string.IsNullOrWhiteSpace(manifest.Sha256))
        {
            throw new Exception(
                "Le manifeste ne contient ni liste de fichiers ni package legacy."
            );
        }

        if (manifest.Updater is not null &&
            (!string.IsNullOrWhiteSpace(manifest.Updater.DownloadUrl) ||
             !string.IsNullOrWhiteSpace(manifest.Updater.Sha256)))
        {
            if (string.IsNullOrWhiteSpace(manifest.Updater.DownloadUrl) ||
                string.IsNullOrWhiteSpace(manifest.Updater.Sha256) ||
                string.IsNullOrWhiteSpace(manifest.Updater.Version))
                throw new Exception("La section updater du manifeste est invalide.");
        }

        return manifest;
    }

    // A GitHub Release download can temporarily return 502/503/504 (or 429).
    // Retry only transient network failures, always rewriting the temporary file.
    // SHA-256 validation remains the caller's responsibility before installation.
    private static async Task DownloadWithRetryAsync(
        string url,
        string destination,
        TimeSpan timeout,
        Action<string>? log)
    {
        const int maxAttempts = 4;
        using var handler = new HttpClientHandler { AllowAutoRedirect = true };
        using var http = new HttpClient(handler) { Timeout = timeout };
        http.DefaultRequestHeaders.UserAgent.ParseAdd(
            "Le-Sanglot-des-Goelands-Updater/3.4");

        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            try
            {
                using var response = await http.GetAsync(
                    url, HttpCompletionOption.ResponseHeadersRead);
                response.EnsureSuccessStatusCode();

                await using var input = await response.Content.ReadAsStreamAsync();
                await using (var output = new FileStream(
                    destination, FileMode.Create, FileAccess.Write,
                    FileShare.None, 81920, useAsync: true))
                {
                    await input.CopyToAsync(output);
                }
                return;
            }
            catch (Exception ex) when (IsTransientDownloadError(ex))
            {
                TryDeleteFile(destination);
                if (attempt == maxAttempts)
                    throw;
                int delaySeconds = 2 * (1 << (attempt - 1));
                log?.Invoke(
                    $"Erreur temporaire de téléchargement : {ex.Message} " +
                    $"Nouvel essai {attempt + 1}/{maxAttempts} dans {delaySeconds} s...");
                await Task.Delay(TimeSpan.FromSeconds(delaySeconds));
            }
        }
    }

    private static bool IsTransientDownloadError(Exception ex)
    {
        if (ex is HttpRequestException httpEx)
        {
            if (httpEx.StatusCode is null)
                return true; // Connexion perdue / erreur réseau sans statut HTTP.
            int status = (int)httpEx.StatusCode.Value;
            return status == 408 || status == 429 || status == 500 ||
                   status == 502 || status == 503 || status == 504;
        }
        return ex is TaskCanceledException || ex is IOException;
    }

    public static string ComputeFileSha256(string path)
        => ComputeSha256(path);

    public static async Task DownloadFileVerifiedAsync(
        string url,
        string sha256,
        string destination,
        Action<string>? log = null)
    {
        log?.Invoke("Téléchargement du composant de mise à jour...");
        await DownloadWithRetryAsync(
            url, destination, TimeSpan.FromMinutes(10), log);

        string actual = ComputeSha256(destination);
        if (!actual.Equals(sha256.Trim(), StringComparison.OrdinalIgnoreCase))
        {
            TryDeleteFile(destination);
            throw new Exception(
                $"SHA-256 incorrect pour le composant de mise à jour.\n" +
                $"Attendu : {sha256}\nReçu : {actual}");
        }
    }

    public static string ReadLocalVersion(string gameFolder)
    {
        string p = Path.Combine(gameFolder, LocalVersionFile);
        return File.Exists(p) ? File.ReadAllText(p).Trim() : "0";
    }

    public static SeventhModDetection DetectSeventhMod(string gameFolder)
    {
        if (!Directory.Exists(gameFolder))
            return new(false, "Le dossier du jeu n'existe pas.");

        string versionData = Path.Combine(gameFolder, "installedVersionData.json");
        if (File.Exists(versionData))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(versionData));
                var root = doc.RootElement;

                string id = root.TryGetProperty("id", out var idEl)
                    ? idEl.GetString() ?? ""
                    : "";
                string attempted = root.TryGetProperty(
                    "lastAttemptedInstallID", out var attemptEl)
                    ? attemptEl.GetString() ?? ""
                    : "";

                bool isQuestionFull =
                    id.StartsWith(
                        "Umineko Question (Ch. 1-4)/full",
                        StringComparison.OrdinalIgnoreCase) ||
                    attempted.StartsWith(
                        "Umineko Question (Ch. 1-4)/full",
                        StringComparison.OrdinalIgnoreCase);

                if (isQuestionFull)
                {
                    var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    if (root.TryGetProperty("files", out var filesEl) &&
                        filesEl.ValueKind == JsonValueKind.Array)
                    {
                        foreach (var item in filesEl.EnumerateArray())
                        {
                            if (item.TryGetProperty("id", out var fileId))
                            {
                                string? value = fileId.GetString();
                                if (!string.IsNullOrWhiteSpace(value))
                                    ids.Add(value);
                            }
                        }
                    }

                    if (ids.Contains("script") && ids.Contains("exe"))
                        return new(true,
                            "07th-Mod complet détecté via installedVersionData.json.");
                }
            }
            catch
            {
                // Fall through to marker detection for older/manual installs.
            }
        }

        bool oldface = File.Exists(Path.Combine(
            gameFolder, "fonts", "oldface0.ttf"));

        int secondaryMarkers = 0;
        if (Directory.Exists(Path.Combine(gameFolder, "big"))) secondaryMarkers++;
        if (File.Exists(Path.Combine(gameFolder, "arc4.nsa"))) secondaryMarkers++;
        if (File.Exists(Path.Combine(gameFolder, "EnableSteamSync.bat"))) secondaryMarkers++;
        if (File.Exists(Path.Combine(gameFolder, "Umineko1to4_DebugMode.bat"))) secondaryMarkers++;

        if (oldface && secondaryMarkers >= 1)
            return new(true,
                "Installation 07th-Mod détectée via les fichiers du jeu.");

        return new(false,
            "07th-Mod complet (Full) n'a pas été détecté. " +
            "Installe d'abord le patch 07th-Mod pour Umineko Questions.");
    }

    public static async Task<bool> UpdateToManifestAsync(
        string gameFolder,
        RemoteManifest manifest,
        Action<string>? log = null,
        bool verifyAll = false)
    {
        if (manifest.Requires07thMod)
        {
            var detection = DetectSeventhMod(gameFolder);
            if (!detection.Installed)
                throw new Exception(detection.Reason);
        }

        if (manifest.Files is { Count: > 0 } &&
            manifest.Packages is { Count: > 0 })
        {
            return await UpdateFromFileManifestAsync(
                gameFolder, manifest, log, verifyAll);
        }

        return await UpdateLegacyAsync(gameFolder, manifest, log, verifyAll);
    }

    private static async Task<bool> UpdateFromFileManifestAsync(
        string gameFolder,
        RemoteManifest manifest,
        Action<string>? log,
        bool verifyAll)
    {
        string localVersion = ReadLocalVersion(gameFolder);
        log?.Invoke($"Version locale : {localVersion}");
        log?.Invoke($"Version distante : {manifest.Version}");

        if (localVersion.Equals(manifest.Version,
                StringComparison.OrdinalIgnoreCase) && !verifyAll)
        {
            log?.Invoke("Le patch est déjà à jour.");
            return false;
        }

        var state = LoadLocalState(gameFolder);
        bool trustState = state is not null &&
                          state.Version.Equals(localVersion,
                              StringComparison.OrdinalIgnoreCase);

        var needed = new List<RemoteFile>();
        int checkedCount = 0;

        foreach (var remote in manifest.Files!)
        {
            ValidateRelativePath(remote.Path);
            string dst = SafeDestination(gameFolder, remote.Path);

            bool needsUpdate;
            if (!File.Exists(dst))
            {
                needsUpdate = true;
            }
            else if (!verifyAll && trustState && state!.Files.TryGetValue(
                         NormalizePath(remote.Path), out string? knownHash) &&
                     knownHash.Equals(remote.Sha256,
                         StringComparison.OrdinalIgnoreCase))
            {
                // Fast path: unchanged according to our previous manifest.
                needsUpdate = false;
            }
            else
            {
                checkedCount++;
                string actual = ComputeSha256(dst);
                needsUpdate = !actual.Equals(
                    remote.Sha256,
                    StringComparison.OrdinalIgnoreCase);
            }

            if (needsUpdate)
                needed.Add(remote);
        }

        if (verifyAll)
            log?.Invoke($"Vérification terminée : {checkedCount} fichier(s) contrôlé(s).");

        if (needed.Count == 0)
        {
            ApplyExplicitDeletions(gameFolder, manifest.DeletePaths, log);
            SaveLocalState(gameFolder, manifest);
            File.WriteAllText(
                Path.Combine(gameFolder, LocalVersionFile),
                manifest.Version.Trim());
            log?.Invoke("Tous les fichiers sont déjà à jour.");
            return false;
        }

        long totalBytes = needed.Sum(f => Math.Max(0, f.Size));
        log?.Invoke(
            $"{needed.Count} fichier(s) à mettre à jour" +
            (totalBytes > 0 ? $" ({FormatBytes(totalBytes)})" : "") + ".");

        var packageMap = manifest.Packages!.ToDictionary(
            p => p.Id,
            StringComparer.OrdinalIgnoreCase);

        var groups = needed.GroupBy(
            f => f.PackageId,
            StringComparer.OrdinalIgnoreCase);

        string applyDir = Path.Combine(
            Path.GetTempPath(), $"umineko_fr_apply_{Guid.NewGuid():N}");
        Directory.CreateDirectory(applyDir);

        try
        {
            foreach (var group in groups)
            {
                if (!packageMap.TryGetValue(group.Key, out var package))
                    throw new Exception(
                        $"Package introuvable dans le manifeste : {group.Key}");

                await DownloadAndStagePackageAsync(
                    package,
                    group.ToList(),
                    applyDir,
                    log);
            }

            log?.Invoke("Sauvegarde des fichiers d'origine...");
            BackupOriginalsBeforeApply(applyDir, gameFolder);

            log?.Invoke("Installation des fichiers modifiés...");
            ApplyPatch(applyDir, gameFolder);

            foreach (var remote in needed)
            {
                string installed = SafeDestination(gameFolder, remote.Path);
                if (!File.Exists(installed))
                    throw new Exception(
                        $"Le fichier installé est introuvable : {remote.Path}");

                string actual = ComputeSha256(installed);
                if (!actual.Equals(remote.Sha256,
                    StringComparison.OrdinalIgnoreCase))
                    throw new Exception(
                        $"Vérification finale échouée : {remote.Path}");
            }

            ApplyExplicitDeletions(gameFolder, manifest.DeletePaths, log);
            SaveLocalState(gameFolder, manifest);

            File.WriteAllText(
                Path.Combine(gameFolder, LocalVersionFile),
                manifest.Version.Trim());

            log?.Invoke($"Version {manifest.Version} installée.");
            return true;
        }
        finally
        {
            TryDeleteDir(applyDir);
        }
    }

    private static async Task DownloadAndStagePackageAsync(
        RemotePackage package,
        List<RemoteFile> neededFiles,
        string applyDir,
        Action<string>? log)
    {
        string tempZip = Path.Combine(
            Path.GetTempPath(), $"umineko_fr_pkg_{Guid.NewGuid():N}.zip");
        string extractDir = Path.Combine(
            Path.GetTempPath(), $"umineko_fr_pkg_{Guid.NewGuid():N}");

        try
        {
            log?.Invoke($"Téléchargement : {package.Id}...");
            await DownloadWithRetryAsync(
                package.DownloadUrl, tempZip, TimeSpan.FromMinutes(30), log);

            log?.Invoke($"Vérification : {package.Id}...");
            string actualPackageHash = ComputeSha256(tempZip);
            if (!actualPackageHash.Equals(package.Sha256.Trim(),
                StringComparison.OrdinalIgnoreCase))
                throw new Exception(
                    $"SHA-256 incorrect pour le package {package.Id}.\n" +
                    $"Attendu : {package.Sha256}\nReçu : {actualPackageHash}");

            Directory.CreateDirectory(extractDir);
            ZipFile.ExtractToDirectory(tempZip, extractDir);

            foreach (var file in neededFiles)
            {
                ValidateRelativePath(file.Path);
                string src = SafeDestination(extractDir, file.Path);
                if (!File.Exists(src))
                    throw new Exception(
                        $"{file.Path} est absent du package {package.Id}.");

                string srcHash = ComputeSha256(src);
                if (!srcHash.Equals(file.Sha256,
                    StringComparison.OrdinalIgnoreCase))
                    throw new Exception(
                        $"SHA-256 incorrect pour {file.Path} dans {package.Id}.");

                string dst = SafeDestination(applyDir, file.Path);
                Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
                File.Copy(src, dst, overwrite: true);
            }
        }
        finally
        {
            TryDeleteFile(tempZip);
            TryDeleteDir(extractDir);
        }
    }

    private static async Task<bool> UpdateLegacyAsync(
        string gameFolder,
        RemoteManifest manifest,
        Action<string>? log,
        bool forceRepair = false)
    {
        string localVersion = ReadLocalVersion(gameFolder);
        log?.Invoke($"Version locale : {localVersion}");
        log?.Invoke($"Version distante : {manifest.Version}");

        if (localVersion.Equals(manifest.Version,
            StringComparison.OrdinalIgnoreCase) && !forceRepair)
        {
            log?.Invoke("Le patch est déjà à jour.");
            return false;
        }

        if (forceRepair)
        {
            log?.Invoke(
                "Ancien format de manifeste détecté : réparation complète du patch.");
        }

        if (string.IsNullOrWhiteSpace(manifest.DownloadUrl) ||
            string.IsNullOrWhiteSpace(manifest.Sha256))
            throw new Exception("Package legacy absent du manifeste.");

        string tempZip = Path.Combine(
            Path.GetTempPath(), $"umineko_fr_{Guid.NewGuid():N}.zip");
        string tempDir = Path.Combine(
            Path.GetTempPath(), $"umineko_fr_{Guid.NewGuid():N}");

        try
        {
            log?.Invoke($"Téléchargement de la version {manifest.Version}...");
            await DownloadWithRetryAsync(
                manifest.DownloadUrl, tempZip, TimeSpan.FromMinutes(30), log);

            log?.Invoke("Vérification SHA-256...");
            string actual = ComputeSha256(tempZip);
            if (!actual.Equals(manifest.Sha256.Trim(),
                StringComparison.OrdinalIgnoreCase))
                throw new Exception(
                    $"SHA-256 incorrect.\nAttendu : {manifest.Sha256}\nReçu : {actual}");

            Directory.CreateDirectory(tempDir);
            ZipFile.ExtractToDirectory(tempZip, tempDir);

            log?.Invoke("Sauvegarde des fichiers d'origine...");
            BackupOriginalsBeforeApply(tempDir, gameFolder);

            log?.Invoke("Installation des fichiers...");
            ApplyPatch(tempDir, gameFolder);

            File.WriteAllText(
                Path.Combine(gameFolder, LocalVersionFile),
                manifest.Version.Trim());

            // A legacy install cannot populate file hashes safely.
            TryDeleteFile(Path.Combine(gameFolder, LocalStateFile));

            log?.Invoke($"Version {manifest.Version} installée.");
            return true;
        }
        finally
        {
            TryDeleteFile(tempZip);
            TryDeleteDir(tempDir);
        }
    }

    public static void BackupOriginalsBeforeApply(
        string sourceDir,
        string gameFolder)
    {
        string backupDir = Path.Combine(gameFolder, BackupDirName);
        string manifestPath = Path.Combine(backupDir, BackupManifestFile);

        Directory.CreateDirectory(backupDir);

        var entries = LoadBackupManifest(manifestPath);
        var known = new HashSet<string>(
            entries.Select(e => NormalizePath(e.RelativePath)),
            StringComparer.OrdinalIgnoreCase
        );

        foreach (string src in Directory.EnumerateFiles(
            sourceDir, "*", SearchOption.AllDirectories))
        {
            string rel = NormalizePath(Path.GetRelativePath(sourceDir, src));
            ValidateRelativePath(rel);

            if (IsUpdaterPlumbing(rel) || known.Contains(rel))
                continue;

            string dst = SafeDestination(gameFolder, rel);
            bool existed = File.Exists(dst);

            if (existed)
            {
                string backupPath = SafeDestination(
                    Path.Combine(backupDir, "files"), rel);
                Directory.CreateDirectory(Path.GetDirectoryName(backupPath)!);
                File.Copy(dst, backupPath, overwrite: true);
            }

            entries.Add(new BackupEntry(rel, existed));
            known.Add(rel);
        }

        SaveBackupManifest(manifestPath, entries);
    }

    public static void ApplyPatch(string sourceDir, string gameFolder)
    {
        foreach (string src in Directory.EnumerateFiles(
            sourceDir, "*", SearchOption.AllDirectories))
        {
            string rel = NormalizePath(Path.GetRelativePath(sourceDir, src));
            ValidateRelativePath(rel);

            if (IsUpdaterPlumbing(rel))
                continue;

            string dst = SafeDestination(gameFolder, rel);
            Directory.CreateDirectory(Path.GetDirectoryName(dst)!);

            string tmp = dst + ".umineko_fr_new";
            File.Copy(src, tmp, overwrite: true);

            if (File.Exists(dst))
            {
                string bak = dst + ".umineko_fr_tmpbak";
                TryDeleteFile(bak);
                File.Replace(tmp, dst, bak, ignoreMetadataErrors: true);
                TryDeleteFile(bak);
            }
            else
            {
                File.Move(tmp, dst);
            }
        }
    }

    private static void ApplyExplicitDeletions(
        string gameFolder,
        List<string>? deletePaths,
        Action<string>? log)
    {
        if (deletePaths is not { Count: > 0 })
            return;

        string backupDir = Path.Combine(gameFolder, BackupDirName);
        string manifestPath = Path.Combine(backupDir, BackupManifestFile);
        var entries = LoadBackupManifest(manifestPath);
        bool changed = false;

        foreach (string raw in deletePaths)
        {
            string rel = NormalizePath(raw);
            ValidateRelativePath(rel);
            string dst = SafeDestination(gameFolder, rel);

            var entry = entries.FirstOrDefault(e =>
                NormalizePath(e.RelativePath).Equals(
                    rel, StringComparison.OrdinalIgnoreCase));

            if (entry is not null && entry.ExistedBefore)
            {
                string backup = SafeDestination(
                    Path.Combine(backupDir, "files"), rel);
                if (File.Exists(backup))
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
                    File.Copy(backup, dst, overwrite: true);
                    log?.Invoke($"Fichier d'origine restauré : {rel}");
                }
            }
            else
            {
                TryDeleteFile(dst);
                log?.Invoke($"Ancien fichier FR supprimé : {rel}");
            }

            if (entry is not null)
            {
                entries.Remove(entry);
                changed = true;
            }
        }

        if (changed)
            SaveBackupManifest(manifestPath, entries);
    }

    public static void RestorePatchFiles(string gameFolder)
    {
        string backupDir = Path.Combine(gameFolder, BackupDirName);
        string manifestPath = Path.Combine(backupDir, BackupManifestFile);

        if (File.Exists(manifestPath))
        {
            var entries = LoadBackupManifest(manifestPath);

            foreach (var entry in entries.AsEnumerable().Reverse())
            {
                string rel = NormalizePath(entry.RelativePath);
                ValidateRelativePath(rel);
                string dst = SafeDestination(gameFolder, rel);

                if (entry.ExistedBefore)
                {
                    string backup = SafeDestination(
                        Path.Combine(backupDir, "files"), rel);

                    if (File.Exists(backup))
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
                        File.Copy(backup, dst, overwrite: true);
                    }
                }
                else
                {
                    TryDeleteFile(dst);
                }
            }
        }

        TryDeleteDir(backupDir);
        TryDeleteFile(Path.Combine(gameFolder, LocalVersionFile));
        TryDeleteFile(Path.Combine(gameFolder, LocalStateFile));
    }

    public static string ComputeSha256(string path)
    {
        using var stream = File.OpenRead(path);
        using var sha = SHA256.Create();
        return Convert.ToHexString(
            sha.ComputeHash(stream)
        ).ToLowerInvariant();
    }

    private static LocalPatchState? LoadLocalState(string gameFolder)
    {
        string path = Path.Combine(gameFolder, LocalStateFile);
        if (!File.Exists(path))
            return null;

        try
        {
            return JsonSerializer.Deserialize<LocalPatchState>(
                File.ReadAllText(path), JsonOptions());
        }
        catch
        {
            return null;
        }
    }

    private static void SaveLocalState(
        string gameFolder,
        RemoteManifest manifest)
    {
        var state = new LocalPatchState
        {
            Version = manifest.Version,
            Files = new Dictionary<string, string>(
                StringComparer.OrdinalIgnoreCase)
        };

        foreach (var file in manifest.Files ?? new List<RemoteFile>())
            state.Files[NormalizePath(file.Path)] = file.Sha256.ToLowerInvariant();

        File.WriteAllText(
            Path.Combine(gameFolder, LocalStateFile),
            JsonSerializer.Serialize(state, new JsonSerializerOptions
            {
                WriteIndented = true
            }));
    }

    private static List<BackupEntry> LoadBackupManifest(string path)
    {
        if (!File.Exists(path))
            return new List<BackupEntry>();

        try
        {
            return JsonSerializer.Deserialize<List<BackupEntry>>(
                File.ReadAllText(path), JsonOptions()) ?? new List<BackupEntry>();
        }
        catch
        {
            return new List<BackupEntry>();
        }
    }

    private static void SaveBackupManifest(
        string path,
        List<BackupEntry> entries)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(
            path,
            JsonSerializer.Serialize(entries, new JsonSerializerOptions
            {
                WriteIndented = true
            }));
    }

    private static bool IsUpdaterPlumbing(string rel)
    {
        rel = NormalizePath(rel);
        return rel.Equals("Umineko1to4.exe",
                    StringComparison.OrdinalIgnoreCase)
            || rel.Equals("Umineko1to4.real.exe",
                    StringComparison.OrdinalIgnoreCase)
            || rel.Equals(ConfigFile,
                    StringComparison.OrdinalIgnoreCase)
            || rel.Equals(LocalVersionFile,
                    StringComparison.OrdinalIgnoreCase)
            || rel.Equals(LocalStateFile,
                    StringComparison.OrdinalIgnoreCase);
    }

    private static string NormalizePath(string path) =>
        path.Replace('\\', '/').TrimStart('/');

    private static void ValidateRelativePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new Exception("Chemin vide dans le manifeste.");

        string normalized = NormalizePath(path);
        if (Path.IsPathRooted(path) ||
            normalized.Equals("..", StringComparison.Ordinal) ||
            normalized.StartsWith("../", StringComparison.Ordinal) ||
            normalized.Contains("/../", StringComparison.Ordinal))
            throw new Exception("Chemin dangereux dans le manifeste : " + path);
    }

    private static string SafeDestination(string root, string relativePath)
    {
        ValidateRelativePath(relativePath);

        string rootFull = Path.GetFullPath(root)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;

        string combined = Path.GetFullPath(Path.Combine(
            root, NormalizePath(relativePath)
                .Replace('/', Path.DirectorySeparatorChar)));

        if (!combined.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
            throw new Exception("Chemin dangereux : " + relativePath);

        return combined;
    }

    private static JsonSerializerOptions JsonOptions() => new()
    {
        PropertyNameCaseInsensitive = true
    };

    private static string FormatBytes(long bytes)
    {
        string[] units = { "o", "Ko", "Mo", "Go" };
        double value = bytes;
        int unit = 0;
        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }
        return $"{value:0.0} {units[unit]}";
    }

    private static void TryDeleteFile(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }

    private static void TryDeleteDir(string path)
    {
        try
        {
            if (Directory.Exists(path))
                Directory.Delete(path, true);
        }
        catch { }
    }
}