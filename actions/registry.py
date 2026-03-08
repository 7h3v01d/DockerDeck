"""
DockerDeck – actions/registry.py
Registry login, push, pull with secure credential handling.
"""

from tkinter import messagebox

from docker_runner import run_docker, run_docker_stream, run_docker_login
from validation import validate_image_name, ValidationError
from utils import safe_thread
from ui_components import console_write


def registry_login(root, reg_fields: dict, output_widget) -> None:
    """
    SECURITY: Password piped via stdin only — never passed as CLI arg.
    Entry field wiped immediately after reading.
    """
    url  = reg_fields["reg_url"].get().strip()
    user = reg_fields["reg_user"].get().strip()
    pwd  = reg_fields["reg_pass"].get()

    if not user or not pwd:
        messagebox.showwarning("Registry Login",
                               "Username and password are required.", parent=root)
        return

    # Wipe entry immediately
    reg_fields["reg_pass"].delete(0, "end")

    args = ["login", url, "-u", user, "--password-stdin"] if url else \
           ["login", "-u", user, "--password-stdin"]
    if url in ("docker.io", ""):
        args = ["login", "-u", user, "--password-stdin"]

    def _do():
        def cb(text):
            root.after(0, lambda t=text: console_write(output_widget, t))
        run_docker_login(args, pwd, cb)

    safe_thread(_do)


def registry_logout(root, reg_fields: dict, output_widget) -> None:
    url = reg_fields["reg_url"].get().strip()
    def _do():
        out, err, rc = run_docker(["logout", url])
        root.after(0, lambda: console_write(output_widget, f"{out or err}\n"))
    safe_thread(_do)


def registry_push(root, reg_fields: dict, output_widget) -> None:
    src = reg_fields["reg_push_img"].get().strip()
    dst = reg_fields["reg_push_tag"].get().strip()
    try:
        src = validate_image_name(src)
        dst = validate_image_name(dst)
    except ValidationError as e:
        messagebox.showerror("Invalid Image Name", str(e), parent=root)
        return

    def _do():
        if src != dst:
            out, err, rc = run_docker(["tag", src, dst])
            root.after(0, lambda: console_write(output_widget, f"[tag] {out or err}\n"))
        root.after(0, lambda: console_write(output_widget, f"Pushing {dst}…\n"))
        def cb(line):
            root.after(0, lambda l=line: console_write(output_widget, l))
        run_docker_stream(["push", dst], cb)
    safe_thread(_do)


def registry_pull(root, reg_fields: dict, output_widget) -> None:
    img = reg_fields["reg_push_tag"].get().strip()
    try:
        img = validate_image_name(img)
    except ValidationError as e:
        messagebox.showerror("Invalid Image Name", str(e), parent=root)
        return
    def _do():
        def cb(line):
            root.after(0, lambda l=line: console_write(output_widget, l))
        run_docker_stream(["pull", img], cb)
    safe_thread(_do)
