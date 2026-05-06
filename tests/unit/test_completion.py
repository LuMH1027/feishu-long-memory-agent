"""深层测试：Shell Completion 模块"""
import os
import sys
import shutil
import uuid
from pathlib import Path

import pytest

from cli.completion import (
    get_shell_type,
    get_completion_script,
    get_install_path,
    install_completion,
    uninstall_completion,
    get_setup_instructions,
    POWERSHELL_COMPLETION,
    BASH_COMPLETION,
    ZSH_COMPLETION,
)


class TestGetShellType:
    def test_returns_powershell_on_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert get_shell_type() == "powershell"

    def test_returns_zsh_when_shell_env_contains_zsh(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("SHELL", "/usr/bin/zsh")
        assert get_shell_type() == "zsh"

    def test_returns_bash_by_default(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("SHELL", "/usr/bin/bash")
        assert get_shell_type() == "bash"

    def test_returns_bash_when_shell_env_empty(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("SHELL", raising=False)
        assert get_shell_type() == "bash"


class TestGetCompletionScript:
    def test_returns_powershell_script(self):
        script = get_completion_script("powershell")
        assert script == POWERSHELL_COMPLETION
        assert "Register-ArgumentCompleter" in script

    def test_returns_bash_script(self):
        script = get_completion_script("bash")
        assert script == BASH_COMPLETION
        assert "complete -F" in script

    def test_returns_zsh_script(self):
        script = get_completion_script("zsh")
        assert script == ZSH_COMPLETION
        assert "#compdef mem" in script

    def test_all_scripts_contain_mem_subcommands(self):
        for shell in ["powershell", "bash", "zsh"]:
            script = get_completion_script(shell)
            for cmd in ["memorize", "search", "list", "watch", "workflow"]:
                assert cmd in script, f"{shell} script missing command: {cmd}"


class TestGetInstallPath:
    def test_powershell_path_contains_documents(self):
        path = get_install_path("powershell")
        assert "PowerShell" in str(path)
        assert path.name == "mem-completion.ps1"

    def test_bash_path_contains_bash_completion(self):
        path = get_install_path("bash")
        assert ".bash_completion.d" in str(path)
        assert path.name == "mem"

    def test_zsh_path_contains_zsh_completions(self):
        path = get_install_path("zsh")
        assert ".zsh" in str(path)
        assert path.name == "_mem"


class TestInstallCompletion:
    def test_installs_script_successfully(self, tmp_path, monkeypatch):
        install_dir = tmp_path / "completion"
        monkeypatch.setattr(
            "cli.completion.get_install_path",
            lambda shell=None: install_dir / "test_completion.sh",
        )
        monkeypatch.setattr("cli.completion.get_completion_script", lambda shell=None: "# test script")

        result = install_completion("bash", force=True)
        assert result["status"] == "ok"
        assert (install_dir / "test_completion.sh").exists()
        assert (install_dir / "test_completion.sh").read_text() == "# test script"

    def test_skips_when_already_installed(self, tmp_path, monkeypatch):
        install_path = tmp_path / "existing.sh"
        install_path.write_text("existing")
        monkeypatch.setattr(
            "cli.completion.get_install_path", lambda shell=None: install_path
        )

        result = install_completion("bash", force=False)
        assert result["status"] == "skipped"
        assert "已存在" in result["message"]

    def test_overwrites_when_force(self, tmp_path, monkeypatch):
        install_path = tmp_path / "existing.sh"
        install_path.write_text("old content")
        monkeypatch.setattr(
            "cli.completion.get_install_path", lambda shell=None: install_path
        )
        monkeypatch.setattr(
            "cli.completion.get_completion_script", lambda shell=None: "new content"
        )

        result = install_completion("bash", force=True)
        assert result["status"] == "ok"
        assert install_path.read_text() == "new content"


class TestUninstallCompletion:
    def test_removes_existing_script(self, tmp_path, monkeypatch):
        install_path = tmp_path / "to_remove.sh"
        install_path.write_text("to be removed")
        monkeypatch.setattr(
            "cli.completion.get_install_path", lambda shell=None: install_path
        )

        result = uninstall_completion("bash")
        assert result["status"] == "ok"
        assert not install_path.exists()

    def test_skips_when_not_installed(self, tmp_path, monkeypatch):
        install_path = tmp_path / "nonexistent.sh"
        monkeypatch.setattr(
            "cli.completion.get_install_path", lambda shell=None: install_path
        )

        result = uninstall_completion("bash")
        assert result["status"] == "skipped"
        assert "不存在" in result["message"]


class TestGetSetupInstructions:
    def test_contains_shell_name(self):
        instructions = get_setup_instructions("bash")
        assert "bash" in instructions

    def test_contains_activation_command(self):
        instructions = get_setup_instructions("powershell")
        assert "mem completion install" in instructions
