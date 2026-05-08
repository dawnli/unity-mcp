using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using MCPForUnity.Editor.Constants;
using UnityEditor;
using UnityEngine;

namespace MCPForUnity.Editor.Helpers
{
    /// <summary>
    /// Provides shared utilities for deriving deterministic project identity information
    /// used by transport clients (hash, name, persistent session id).
    /// </summary>
    [InitializeOnLoad]
    internal static class ProjectIdentityUtility
    {
        private const string SessionPrefKey = EditorPrefKeys.SessionId;
        private static bool _legacyKeyCleared;
        private static string _cachedProjectName = "Unknown";
        private static string _cachedProjectHash = "default";
        private static string _fallbackSessionId;
        private static bool _cacheScheduled;

        static ProjectIdentityUtility()
        {
            ScheduleCacheRefresh();
            EditorApplication.projectChanged += ScheduleCacheRefresh;
        }

        private static void ScheduleCacheRefresh()
        {
            if (_cacheScheduled)
            {
                return;
            }

            _cacheScheduled = true;
            EditorApplication.delayCall += CacheIdentityOnMainThread;
        }

        private static void CacheIdentityOnMainThread()
        {
            EditorApplication.delayCall -= CacheIdentityOnMainThread;
            _cacheScheduled = false;
            UpdateIdentityCache();
        }

        private static void UpdateIdentityCache()
        {
            try
            {
                string dataPath = Application.dataPath;
                if (string.IsNullOrEmpty(dataPath))
                {
                    return;
                }

                _cachedProjectHash = ComputeProjectPathHash(GetProjectRootPath());
                _cachedProjectName = ComputeProjectName(dataPath);
            }
            catch
            {
                // Ignore and keep defaults
            }
        }

        /// <summary>
        /// Returns the SHA256 hash of the normalized absolute project root path,
        /// truncated to 24 characters. This is also the stable HTTP session id.
        /// </summary>
        public static string GetProjectHash()
        {
            EnsureIdentityCache();
            return _cachedProjectHash;
        }

        /// <summary>
        /// Returns a human friendly project name derived from the Assets directory path,
        /// or "Unknown" if the name cannot be determined.
        /// </summary>
        public static string GetProjectName()
        {
            EnsureIdentityCache();
            return _cachedProjectName;
        }

        /// <summary>
        /// Returns the absolute Unity project root path, stripping the trailing Assets folder
        /// from Application.dataPath when present.
        /// </summary>
        public static string GetProjectRootPath()
        {
            try
            {
                string dataPath = Application.dataPath;
                if (string.IsNullOrEmpty(dataPath))
                {
                    return Directory.GetCurrentDirectory();
                }

                string normalized = dataPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                if (string.Equals(Path.GetFileName(normalized), "Assets", StringComparison.OrdinalIgnoreCase))
                {
                    return Path.GetFullPath(Path.GetDirectoryName(normalized) ?? normalized);
                }

                return Path.GetFullPath(normalized);
            }
            catch
            {
                return Directory.GetCurrentDirectory();
            }
        }

        public static string ComputeProjectPathHash(string absoluteProjectPath)
        {
            try
            {
                string normalized = NormalizeProjectRootPath(absoluteProjectPath);
                using SHA256 sha256 = SHA256.Create();
                byte[] bytes = Encoding.UTF8.GetBytes(normalized);
                byte[] hashBytes = sha256.ComputeHash(bytes);
                var sb = new StringBuilder();
                for (int i = 0; i < hashBytes.Length && sb.Length < 24; i++)
                {
                    sb.Append(hashBytes[i].ToString("x2"));
                }
                return sb.ToString(0, 24).ToLowerInvariant();
            }
            catch
            {
                return "default";
            }
        }

        public static string NormalizeProjectRootPath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return string.Empty;
            }

            try
            {
                path = Path.GetFullPath(path);
            }
            catch
            {
                path = path.Trim();
            }

            path = path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
#if UNITY_EDITOR_WIN
            path = path.ToLowerInvariant();
#endif
            return path;
        }

        private static string ComputeProjectName(string dataPath)
        {
            try
            {
                string projectPath = dataPath;
                projectPath = projectPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                if (projectPath.EndsWith("Assets", StringComparison.OrdinalIgnoreCase))
                {
                    projectPath = projectPath[..^6].TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                }

                string name = Path.GetFileName(projectPath);
                return string.IsNullOrEmpty(name) ? "Unknown" : name;
            }
            catch
            {
                return "Unknown";
            }
        }

        /// <summary>
        /// Persists a server-assigned session id.
        /// Safe to call from background threads.
        /// </summary>
        public static void SetSessionId(string sessionId)
        {
            if (string.IsNullOrEmpty(sessionId))
            {
                return;
            }

            EditorApplication.delayCall += () =>
            {
                try
                {
                    string projectHash = GetProjectHash();
                    string projectSpecificKey = $"{SessionPrefKey}_{projectHash}";
                    EditorPrefs.SetString(projectSpecificKey, sessionId);
                }
                catch (Exception ex)
                {
                    McpLog.Warn($"Failed to persist session ID: {ex.Message}");
                }
            };
        }

        /// <summary>
        /// Retrieves the stable plugin session id for this project.
        /// HTTP local routing uses the normalized absolute project path hash directly.
        /// </summary>
        public static string GetOrCreateSessionId()
        {
            try
            {
                return GetProjectHash();
            }
            catch
            {
                // If prefs are unavailable (e.g. during batch tests) fall back to runtime guid.
                if (string.IsNullOrEmpty(_fallbackSessionId))
                {
                    _fallbackSessionId = Guid.NewGuid().ToString();
                }

                return _fallbackSessionId;
            }
        }

        /// <summary>
        /// Clears the persisted session id (mainly for tests).
        /// </summary>
        public static void ResetSessionId()
        {
            try
            {
                // Clear the project-specific session ID
                string projectHash = GetProjectHash();
                string projectSpecificKey = $"{SessionPrefKey}_{projectHash}";

                if (EditorPrefs.HasKey(projectSpecificKey))
                {
                    EditorPrefs.DeleteKey(projectSpecificKey);
                }

                if (!_legacyKeyCleared && EditorPrefs.HasKey(SessionPrefKey))
                {
                    EditorPrefs.DeleteKey(SessionPrefKey);
                    _legacyKeyCleared = true;
                }

                _fallbackSessionId = null;
            }
            catch
            {
                // Ignore
            }
        }

        private static void EnsureIdentityCache()
        {
            // When Application.dataPath is unavailable (e.g., batch mode) we fall back to
            // hashing the current working directory/Assets path so each project still
            // derives a deterministic, per-project session id rather than sharing "default".
            if (!string.IsNullOrEmpty(_cachedProjectHash) && _cachedProjectHash != "default")
            {
                return;
            }

            UpdateIdentityCache();

            if (!string.IsNullOrEmpty(_cachedProjectHash) && _cachedProjectHash != "default")
            {
                return;
            }

            string fallback = TryComputeFallbackProjectHash();
            if (!string.IsNullOrEmpty(fallback))
            {
                _cachedProjectHash = fallback;
            }
        }

        private static string TryComputeFallbackProjectHash()
        {
            try
            {
                string workingDirectory = Directory.GetCurrentDirectory();
                if (string.IsNullOrEmpty(workingDirectory))
                {
                    return "default";
                }

                // Normalise trailing separators so hashes remain stable
                workingDirectory = workingDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                return ComputeProjectPathHash(workingDirectory);
            }
            catch
            {
                return "default";
            }
        }
    }
}
