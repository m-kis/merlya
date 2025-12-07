"""
Merlya SSH - SFTP helper mixin.

Provides SFTP operations reused by the SSH pool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    from merlya.ssh.pool import SSHPool


class SFTPOperations:
    """SFTP operations shared by the SSH pool."""

    async def upload_file(  # type: ignore[misc]
        self: SSHPool,
        host: str,
        local_path: str | Path,
        remote_path: str,
        **conn_kwargs: Any,
    ) -> None:
        """
        Upload a file to remote host via SFTP.

        Args:
            host: Target host.
            local_path: Local file path.
            remote_path: Remote destination path.
            **conn_kwargs: Connection options (port, username, etc.).

        Raises:
            FileNotFoundError: If local file doesn't exist.
            asyncssh.SFTPError: If upload fails.
        """
        from pathlib import Path as PathlibPath

        local = PathlibPath(local_path).expanduser()
        if not local.exists():
            raise FileNotFoundError(f"Local file not found: {local}")

        conn = await self.get_connection(host, **conn_kwargs)
        if conn.connection is None:
            raise RuntimeError(f"Connection to {host} is closed")

        async with conn.connection.start_sftp_client() as sftp:
            await sftp.put(str(local), remote_path)
            logger.info(f"📤 Uploaded {local.name} -> {host}:{remote_path}")

    async def download_file(  # type: ignore[misc]
        self: SSHPool,
        host: str,
        remote_path: str,
        local_path: str | Path,
        **conn_kwargs: Any,
    ) -> None:
        """
        Download a file from remote host via SFTP.

        Args:
            host: Target host.
            remote_path: Remote file path.
            local_path: Local destination path.
            **conn_kwargs: Connection options (port, username, etc.).

        Raises:
            asyncssh.SFTPError: If download fails.
        """
        from pathlib import Path as PathlibPath

        local = PathlibPath(local_path).expanduser()
        local.parent.mkdir(parents=True, exist_ok=True)

        conn = await self.get_connection(host, **conn_kwargs)
        if conn.connection is None:
            raise RuntimeError(f"Connection to {host} is closed")

        async with conn.connection.start_sftp_client() as sftp:
            await sftp.get(remote_path, str(local))
            logger.info(f"📥 Downloaded {host}:{remote_path} -> {local.name}")

    async def list_remote_dir(  # type: ignore[misc]
        self: SSHPool,
        host: str,
        remote_path: str = ".",
        **conn_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        List remote directory contents via SFTP.

        Args:
            host: Target host.
            remote_path: Remote directory path.
            **conn_kwargs: Connection options.

        Returns:
            List of file info dicts with name, size, is_dir, permissions.
        """
        conn = await self.get_connection(host, **conn_kwargs)
        if conn.connection is None:
            raise RuntimeError(f"Connection to {host} is closed")

        result = []
        async with conn.connection.start_sftp_client() as sftp:
            async for entry in sftp.scandir(remote_path):
                result.append(
                    {
                        "name": entry.filename,
                        "size": entry.attrs.size,
                        "is_dir": entry.attrs.type == 2,  # SSH_FILEXFER_TYPE_DIRECTORY
                        "permissions": oct(entry.attrs.permissions)
                        if entry.attrs.permissions
                        else None,
                        "mtime": entry.attrs.mtime,
                    }
                )

        return result

    async def read_remote_file(  # type: ignore[misc]
        self: SSHPool,
        host: str,
        remote_path: str,
        **conn_kwargs: Any,
    ) -> str:
        """
        Read a remote file content via SFTP.

        Args:
            host: Target host.
            remote_path: Remote file path.
            **conn_kwargs: Connection options.

        Returns:
            File content as string.
        """
        conn = await self.get_connection(host, **conn_kwargs)
        if conn.connection is None:
            raise RuntimeError(f"Connection to {host} is closed")

        async with conn.connection.start_sftp_client() as sftp, sftp.open(remote_path, "r") as f:
            content = await f.read()
            return content.decode("utf-8") if isinstance(content, bytes) else content

    async def write_remote_file(  # type: ignore[misc]
        self: SSHPool,
        host: str,
        remote_path: str,
        content: str,
        **conn_kwargs: Any,
    ) -> None:
        """
        Write content to a remote file via SFTP.

        Args:
            host: Target host.
            remote_path: Remote file path.
            content: Content to write.
            **conn_kwargs: Connection options.
        """
        conn = await self.get_connection(host, **conn_kwargs)
        if conn.connection is None:
            raise RuntimeError(f"Connection to {host} is closed")

        async with conn.connection.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "w") as f:
                await f.write(content)
            logger.debug(f"📝 Wrote {len(content)} bytes to {host}:{remote_path}")
