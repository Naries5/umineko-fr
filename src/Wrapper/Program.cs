using System.Diagnostics;
using System.Text.Json;
using UminekoFR;

namespace UminekoFRWrapper;

internal static class Program
{
    private const string RealExe = "Umineko1to4.real.exe";
    private const string WrapperExe = "Umineko1to4.exe";
    private const string LogFile = "umineko_fr_updater.log";

    [STAThread]
    private static async Task<int> Main(string[] args)
    {
        if (args.Length >= 3 &&
            args[0].Equals("--self-replace", StringComparison.OrdinalIgnoreCase))
        {
            return await SelfReplaceAsync(args[1], args[2]);
        }

        string root = AppContext.BaseDirectory;

        try
        {
            Log(root, "=== Lancement updater v3.4 ===");

            var mod = UpdaterCore.DetectSeventhMod(root);
            if (!mod.Installed)
            {
                Log(root, "07th-Mod non détecté : " + mod.Reason);
                return LaunchAndWait(root);
            }

            string configPath = Path.Combine(root, UpdaterCore.ConfigFile);
            if (File.Exists(configPath))
            {
                var cfg = JsonSerializer.Deserialize<UpdaterConfig>(
                    await File.ReadAllTextAsync(configPath),
                    new JsonSerializerOptions
                    {
                        PropertyNameCaseInsensitive = true
                    });

                if (cfg is not null)
                {
                    try
                    {
                        var manifest = await UpdaterCore.GetRemoteManifestAsync(
                            cfg.ManifestUrl, cfg.TimeoutSeconds);

                        if (await TrySelfUpdateAsync(root, manifest))
                            return 0;

                        Log(root,
                            $"Version locale={UpdaterCore.ReadLocalVersion(root)}, " +
                            $"distante={manifest.Version}");

                        bool changed = await UpdaterCore.UpdateToManifestAsync(
                            root, manifest,
                            msg => Log(root, msg),
                            verifyAll: false);

                        if (changed)
                            Log(root, $"Mise à jour {manifest.Version} installée.");
                    }
                    catch (Exception ex)
                    {
                        Log(root, "Update impossible: " + ex.Message);
                        if (!cfg.LaunchIfUpdateFails)
                            return 10;
                    }
                }
            }

            return LaunchAndWait(root);
        }
        catch (Exception ex)
        {
            Log(root, "ERREUR FATALE: " + ex);
            try { return LaunchAndWait(root); }
            catch { return 99; }
        }
    }

    private static async Task<bool> TrySelfUpdateAsync(
        string root, RemoteManifest manifest)
    {
        var updater = manifest.Updater;
        if (updater is null ||
            string.IsNullOrWhiteSpace(updater.DownloadUrl) ||
            string.IsNullOrWhiteSpace(updater.Sha256))
            return false;

        string target = Path.Combine(root, WrapperExe);
        if (!File.Exists(target))
            return false;

        string currentHash = UpdaterCore.ComputeFileSha256(target);
        if (currentHash.Equals(
            updater.Sha256.Trim(), StringComparison.OrdinalIgnoreCase))
            return false;

        string temp = Path.Combine(
            Path.GetTempPath(),
            $"UminekoFR-Updater-{Guid.NewGuid():N}.exe");

        try
        {
            Log(root, $"Nouvel updater disponible : {updater.Version}.");
            await UpdaterCore.DownloadFileVerifiedAsync(
                updater.DownloadUrl, updater.Sha256, temp,
                msg => Log(root, msg));

            int pid = Environment.ProcessId;
            Process.Start(new ProcessStartInfo
            {
                FileName = temp,
                Arguments = $"--self-replace \"{target}\" {pid}",
                WorkingDirectory = root,
                UseShellExecute = true
            });

            Log(root, "Passage de relais au nouvel updater.");
            return true;
        }
        catch
        {
            try { if (File.Exists(temp)) File.Delete(temp); } catch { }
            throw;
        }
    }

    private static async Task<int> SelfReplaceAsync(
        string target, string oldPidText)
    {
        int.TryParse(oldPidText, out int oldPid);

        if (oldPid > 0)
        {
            try
            {
                using var old = Process.GetProcessById(oldPid);
                await old.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(30));
            }
            catch { }
        }

        Exception? last = null;
        for (int i = 0; i < 40; i++)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(Environment.ProcessPath!, target, overwrite: true);
                last = null;
                break;
            }
            catch (Exception ex)
            {
                last = ex;
                await Task.Delay(250);
            }
        }

        if (last is not null)
            return 31;

        Process.Start(new ProcessStartInfo
        {
            FileName = target,
            WorkingDirectory = Path.GetDirectoryName(target)!,
            UseShellExecute = true
        });

        return 0;
    }

    private static int LaunchAndWait(string root)
    {
        string exe = Path.Combine(root, RealExe);
        if (!File.Exists(exe))
        {
            Log(root, $"Jeu réel introuvable: {RealExe}");
            return 20;
        }

        var p = Process.Start(new ProcessStartInfo
        {
            FileName = exe, WorkingDirectory = root, UseShellExecute = true
        });

        if (p is null)
            return 21;

        p.WaitForExit();
        return p.ExitCode;
    }

    private static void Log(string root, string message)
    {
        try
        {
            File.AppendAllText(
                Path.Combine(root, LogFile),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] " +
                message + Environment.NewLine
            );
        }
        catch { }
    }
}
