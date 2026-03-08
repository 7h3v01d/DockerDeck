"""
DockerDeck – actions/images.py
Image tab actions: pull, inspect, run, remove, prune.
"""

from tkinter import messagebox
from docker_runner import run_docker, run_docker_stream
from validation import validate_image_name, ValidationError
from utils import safe_thread
from ui_components import console_write, get_tree_widget


def image_pull(root, pull_entry, output_widget, status_fn=None) -> None:
    image = pull_entry.get().strip()
    if not image:
        return
    try:
        image = validate_image_name(image)
    except ValidationError as e:
        messagebox.showerror("Invalid Image Name", str(e), parent=root)
        return
    def _do():
        if status_fn:
            status_fn(f"Pulling {image}…")
        root.after(0, lambda: console_write(
            output_widget, f"Pulling {image}…\n", clear=True))
        def cb(line):
            root.after(0, lambda l=line: console_write(output_widget, l))
        run_docker_stream(["pull", image], cb)
        if status_fn:
            status_fn(f"Pull complete: {image}")
    safe_thread(_do)


def image_inspect(root, images_tree, output_widget) -> None:
    tree = get_tree_widget(images_tree)
    sel = tree.selection() if tree else []
    if not sel:
        messagebox.showinfo("Select Image", "Please select an image.", parent=root)
        return
    vals = tree.item(sel[0])["values"]
    image_id = vals[2]
    def _do():
        out, err, _ = run_docker(["inspect", image_id])
        root.after(0, lambda: console_write(
            output_widget, f"=== inspect {image_id} ===\n{out or err}\n\n"))
    safe_thread(_do)


def image_run(root, images_tree, deploy_fields, validate_fn, nb, tab_index: int = 3) -> None:
    """Pre-fill Deploy tab with selected image and switch to it."""
    tree = get_tree_widget(images_tree)
    sel = tree.selection() if tree else []
    if not sel:
        messagebox.showinfo("Select Image", "Please select an image.", parent=root)
        return
    vals = tree.item(sel[0])["values"]
    img = f"{vals[0]}:{vals[1]}"
    deploy_fields["deploy_image"].delete(0, "end")
    deploy_fields["deploy_image"].insert(0, img)
    if validate_fn:
        validate_fn("deploy_image")
    nb.select(tab_index)


def image_remove(root, images_tree, output_widget) -> None:
    tree = get_tree_widget(images_tree)
    sel = tree.selection() if tree else []
    if not sel:
        messagebox.showinfo("Select Image", "Please select an image.", parent=root)
        return
    vals = tree.item(sel[0])["values"]
    image_id = vals[2]
    if messagebox.askyesno("Remove Image",
                            f"Remove image '{vals[0]}:{vals[1]}'?", parent=root):
        def _do():
            out, err, rc = run_docker(["rmi", image_id])
            root.after(0, lambda: console_write(
                output_widget,
                f"[rmi {image_id}]  rc={rc}\n{out or err}\n\n"))
        safe_thread(_do)


def image_prune(root, output_widget) -> None:
    if messagebox.askyesno("Prune Images", "Remove all dangling images?", parent=root):
        def _do():
            out, err, rc = run_docker(["image", "prune", "-f"])
            root.after(0, lambda: console_write(
                output_widget, f"[image prune]\n{out or err}\n\n"))
        safe_thread(_do)
