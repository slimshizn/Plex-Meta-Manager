import os, re, time
from PIL import Image, ImageColor, ImageDraw, ImageFont
from modules import util
from modules.util import Failed

logger = util.logger

portrait_dim = (1000, 1500)
landscape_dim = (1920, 1080)
rating_mods = ["0", "%", "#"]
special_text_overlays = [f"text({a}{s})" for a in ["audience_rating", "critic_rating", "user_rating"] for s in [""] + rating_mods]

def parse_cords(data, parent, required=False):
    horizontal_align = util.parse("Overlay", "horizontal_align", data["horizontal_align"], parent=parent,
                                  options=["left", "center", "right"]) if "horizontal_align" in data else "left"
    vertical_align = util.parse("Overlay", "vertical_align", data["vertical_align"], parent=parent,
                                options=["top", "center", "bottom"]) if "vertical_align" in data else "top"

    horizontal_offset = None
    if "horizontal_offset" in data and data["horizontal_offset"] is not None:
        x_off = data["horizontal_offset"]
        per = False
        if str(x_off).endswith("%"):
            x_off = x_off[:-1]
            per = True
        x_off = util.check_num(x_off)
        error = f"Overlay Error: {parent} horizontal_offset: {data['horizontal_offset']} must be a number"
        if x_off is None:
            raise Failed(error)
        if horizontal_align != "center" and not per and x_off < 0:
            raise Failed(f"{error} 0 or greater")
        elif horizontal_align != "center" and per and (x_off > 100 or x_off < 0):
            raise Failed(f"{error} between 0% and 100%")
        elif horizontal_align == "center" and per and (x_off > 50 or x_off < -50):
            raise Failed(f"{error} between -50% and 50%")
        horizontal_offset = f"{x_off}%" if per else x_off
    if horizontal_offset is None and horizontal_align == "center":
        horizontal_offset = 0
    if required and horizontal_offset is None:
        raise Failed(f"Overlay Error: {parent} horizontal_offset is required")

    vertical_offset = None
    if "vertical_offset" in data and data["vertical_offset"] is not None:
        y_off = data["vertical_offset"]
        per = False
        if str(y_off).endswith("%"):
            y_off = y_off[:-1]
            per = True
        y_off = util.check_num(y_off)
        error = f"Overlay Error: {parent} vertical_offset: {data['vertical_offset']} must be a number"
        if y_off is None:
            raise Failed(error)
        if vertical_align != "center" and not per and y_off < 0:
            raise Failed(f"{error} 0 or greater")
        elif vertical_align != "center" and per and (y_off > 100 or y_off < 0):
            raise Failed(f"{error} between 0% and 100%")
        elif vertical_align == "center" and per and (y_off > 50 or y_off < -50):
            raise Failed(f"{error} between -50% and 50%")
        vertical_offset = f"{y_off}%" if per else y_off
    if vertical_offset is None and vertical_align == "center":
        vertical_offset = 0
    if required and vertical_offset is None:
        raise Failed(f"Overlay Error: {parent} vertical_offset is required")

    return horizontal_align, horizontal_offset, vertical_align, vertical_offset


class Overlay:
    def __init__(self, config, library, original_mapping_name, overlay_data, suppress):
        self.config = config
        self.library = library
        self.original_mapping_name = original_mapping_name
        self.data = overlay_data
        self.suppress = suppress
        self.keys = []
        self.updated = False
        self.image = None
        self.landscape = None
        self.landscape_box = None
        self.portrait = None
        self.portrait_box = None
        self.group = None
        self.queue = None
        self.weight = None
        self.path = None
        self.font = None
        self.font_name = None
        self.font_size = 36
        self.font_color = None
        self.addon_offset = 0
        self.addon_position = None

        logger.debug("")
        logger.debug("Validating Method: overlay")
        logger.debug(f"Value: {self.data}")
        if not isinstance(self.data, dict):
            self.data = {"name": str(self.data)}
            logger.warning(f"Overlay Warning: No overlay attribute using mapping name {self.data} as the overlay name")
        if "name" not in self.data or not self.data["name"]:
            raise Failed(f"Overlay Error: overlay must have the name attribute")
        self.name = str(self.data["name"])
        if self.original_mapping_name not in library.overlay_names:
            library.overlay_names.append(self.original_mapping_name)
            self.mapping_name = self.original_mapping_name
        else:
            name_count = 1
            test_name = f"{self.original_mapping_name} ({name_count})"
            while test_name in library.overlay_names:
                name_count += 1
                test_name = f"{self.original_mapping_name} ({name_count})"
            library.overlay_names.append(test_name)
            self.mapping_name = test_name

        if "group" in self.data and self.data["group"]:
            self.group = str(self.data["group"])
        if "queue" in self.data and self.data["queue"]:
            self.queue = str(self.data["queue"])
        if "weight" in self.data:
            self.weight = util.parse("Overlay", "weight", self.data["weight"], datatype="int", parent="overlay", minimum=0)
        if "group" in self.data and (self.weight is None or not self.group):
            raise Failed(f"Overlay Error: overlay attribute's group requires the weight attribute")
        elif "queue" in self.data and (self.weight is None or not self.queue):
            raise Failed(f"Overlay Error: overlay attribute's queue requires the weight attribute")
        elif self.group and self.queue:
            raise Failed(f"Overlay Error: overlay attribute's group and queue cannot be used together")
        self.horizontal_align, self.horizontal_offset, self.vertical_align, self.vertical_offset = parse_cords(self.data, "overlay")

        if (self.horizontal_offset is None and self.vertical_offset is not None) or (self.vertical_offset is None and self.horizontal_offset is not None):
            raise Failed(f"Overlay Error: overlay attribute's horizontal_offset and vertical_offset must be used together")

        def color(attr):
            if attr in self.data and self.data[attr]:
                try:
                    return ImageColor.getcolor(self.data[attr], "RGBA")
                except ValueError:
                    raise Failed(f"Overlay Error: overlay {attr}: {self.data[attr]} invalid")
        self.back_color = color("back_color")
        self.back_radius = util.parse("Overlay", "back_radius", self.data["back_radius"], datatype="int", parent="overlay") if "back_radius" in self.data else None
        self.back_line_width = util.parse("Overlay", "back_line_width", self.data["back_line_width"], datatype="int", parent="overlay") if "back_line_width" in self.data else None
        self.back_line_color = color("back_line_color")
        self.back_padding = util.parse("Overlay", "back_padding", self.data["back_padding"], datatype="int", parent="overlay", default=0) if "back_padding" in self.data else 0
        self.back_align = util.parse("Overlay", "back_align", self.data["back_align"], parent="overlay", default="center", options=["left", "right", "center", "top", "bottom"]) if "back_align" in self.data else "center"
        self.back_box = None
        back_width = util.parse("Overlay", "back_width", self.data["back_width"], datatype="int", parent="overlay", minimum=0) if "back_width" in self.data else -1
        back_height = util.parse("Overlay", "back_height", self.data["back_height"], datatype="int", parent="overlay", minimum=0) if "back_height" in self.data else -1
        if (back_width >= 0 and back_height < 0) or (back_height >= 0 and back_width < 0):
            raise Failed(f"Overlay Error: overlay attributes back_width and back_height must be used together")
        if self.back_align != "center" and (back_width < 0 or back_height < 0):
            raise Failed(f"Overlay Error: overlay attribute back_align only works when back_width and back_height are used")
        elif back_width >= 0 and back_height >= 0:
            self.back_box = (back_width, back_height)
        self.has_back = True if self.back_color or self.back_line_color else False
        if self.has_back and not self.has_coordinates() and not self.queue:
            raise Failed(f"Overlay Error: horizontal_offset and vertical_offset are required when using a backdrop")

        def get_and_save_image(image_url):
            response = self.config.get(image_url)
            if response.status_code >= 400:
                raise Failed(f"Overlay Error: Overlay Image not found at: {image_url}")
            if "Content-Type" not in response.headers or response.headers["Content-Type"] != "image/png":
                raise Failed(f"Overlay Error: Overlay Image not a png: {image_url}")
            if not os.path.exists(library.overlay_folder) or not os.path.isdir(library.overlay_folder):
                os.makedirs(library.overlay_folder, exist_ok=False)
                logger.info(f"Creating Overlay Folder found at: {library.overlay_folder}")
            clean_image_name, _ = util.validate_filename(self.name)
            image_path = os.path.join(library.overlay_folder, f"{clean_image_name}.png")
            if os.path.exists(image_path):
                os.remove(image_path)
            with open(image_path, "wb") as handler:
                handler.write(response.content)
            while util.is_locked(image_path):
                time.sleep(1)
            return image_path

        if not self.name.startswith("blur"):
            if "file" in self.data and self.data["file"]:
                self.path = self.data["file"]
            elif "git" in self.data and self.data["git"]:
                self.path = get_and_save_image(f"{self.config.GitHub.configs_url}{self.data['git']}.png")
            elif "repo" in self.data and self.data["repo"]:
                self.path = get_and_save_image(f"{self.config.custom_repo}{self.data['repo']}.png")
            elif "url" in self.data and self.data["url"]:
                self.path = get_and_save_image(self.data["url"])

        if "|" in self.name:
            raise Failed(f"Overlay Error: Overlay Name: {self.name} cannot contain '|'")
        elif self.name.startswith("blur"):
            try:
                match = re.search("\\(([^)]+)\\)", self.name)
                if not match or 0 >= int(match.group(1)) > 100:
                    raise ValueError
                self.name = f"blur({match.group(1)})"
            except ValueError:
                logger.error(f"Overlay Error: failed to parse overlay blur name: {self.name} defaulting to blur(50)")
                self.name = "blur(50)"
        elif self.name.startswith("text"):
            if not self.has_coordinates() and not self.queue:
                raise Failed(f"Overlay Error: overlay attribute's horizontal_offset and vertical_offset are required when using text")
            if self.path:
                if not os.path.exists(self.path):
                    raise Failed(f"Overlay Error: Text Overlay Addon Image not found at: {self.path}")
                self.addon_offset = util.parse("Overlay", "addon_offset", self.data["addon_offset"], datatype="int", parent="overlay") if "addon_offset" in self.data else 0
                self.addon_position = util.parse("Overlay", "addon_position", self.data["addon_position"], parent="overlay", options=["left", "right", "top", "bottom"]) if "addon_position" in self.data else "left"
                image_compare = None
                if self.config.Cache:
                    _, image_compare, _ = self.config.Cache.query_image_map(self.mapping_name, f"{self.library.image_table_name}_overlays")
                overlay_size = os.stat(self.path).st_size
                self.updated = not image_compare or str(overlay_size) != str(image_compare)
                try:
                    self.image = Image.open(self.path).convert("RGBA")
                    if self.config.Cache:
                        self.config.Cache.update_image_map(self.mapping_name, f"{self.library.image_table_name}_overlays", self.name, overlay_size)
                except OSError:
                    raise Failed(f"Overlay Error: overlay image {self.path} failed to load")
            match = re.search("\\(([^)]+)\\)", self.name)
            if not match:
                raise Failed(f"Overlay Error: failed to parse overlay text name: {self.name}")
            self.name = f"text({match.group(1)})"
            self.font_name = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "Roboto-Medium.ttf")
            if "font_size" in self.data:
                self.font_size = util.parse("Overlay", "font_size", self.data["font_size"], datatype="int", parent="overlay", default=self.font_size)
            if "font" in self.data and self.data["font"]:
                font = str(self.data["font"])
                if not os.path.exists(font):
                    fonts = util.get_system_fonts()
                    if font not in fonts:
                        raise Failed(f"Overlay Error: font: {font} not found. Options: {', '.join(fonts)}")
                self.font_name = font
            self.font = ImageFont.truetype(self.font_name, self.font_size)
            if "font_style" in self.data and self.data["font_style"]:
                try:
                    variation_names = [n.decode("utf-8") for n in self.font.get_variation_names()]
                    if self.data["font_style"] in variation_names:
                        self.font.set_variation_by_name(self.data["font_style"])
                    else:
                        raise Failed(f"Overlay Error: Font Style {self.data['font_style']} not found. Options: {','.join(variation_names)}")
                except OSError:
                    logger.warning(f"Overlay Warning: font: {self.font} does not have variations")
            self.font_color = None
            if "font_color" in self.data and self.data["font_color"]:
                try:
                    self.font_color = ImageColor.getcolor(self.data["font_color"], "RGBA")
                except ValueError:
                    raise Failed(f"Overlay Error: overlay font_color: {self.data['font_color']} invalid")
            if self.name not in special_text_overlays:
                box = self.image.size if self.image else None
                self.portrait, self.portrait_box = self.get_backdrop(portrait_dim, box=box, text=self.name[5:-1])
                self.landscape, self.landscape_box = self.get_backdrop(landscape_dim, box=box, text=self.name[5:-1])
        else:
            if not self.path:
                clean_name, _ = util.validate_filename(self.name)
                self.path = os.path.join(library.overlay_folder, f"{clean_name}.png")
            if not os.path.exists(self.path):
                raise Failed(f"Overlay Error: Overlay Image not found at: {self.path}")
            image_compare = None
            if self.config.Cache:
                _, image_compare, _ = self.config.Cache.query_image_map(self.mapping_name, f"{self.library.image_table_name}_overlays")
            overlay_size = os.stat(self.path).st_size
            self.updated = not image_compare or str(overlay_size) != str(image_compare)
            try:
                self.image = Image.open(self.path).convert("RGBA")
                if self.has_coordinates():
                    self.portrait, self.portrait_box = self.get_backdrop(portrait_dim, box=self.image.size)
                    self.landscape, self.landscape_box = self.get_backdrop(landscape_dim, box=self.image.size)
                if self.config.Cache:
                    self.config.Cache.update_image_map(self.mapping_name, f"{self.library.image_table_name}_overlays", self.mapping_name, overlay_size)
            except OSError:
                raise Failed(f"Overlay Error: overlay image {self.path} failed to load")

    def get_backdrop(self, canvas_box, box=None, text=None, new_cords=None):
        overlay_image = None
        text_width = None
        text_height = None
        image_width, image_height = box if box else (None, None)
        if text is not None:
            _, _, text_width, text_height = self.get_text_size(text)
            if image_width is not None and self.addon_position in ["left", "right"]:
                box = (text_width + image_width + self.addon_offset, text_height if text_height > image_height else image_height)
            elif image_width is not None:
                box = (text_width if text_width > image_width else image_width, text_height + image_height + self.addon_offset)
            else:
                box = (text_width, text_height)
        box_width, box_height = box
        back_width, back_height = self.back_box if self.back_box else (None, None)
        start_x, start_y = self.get_coordinates(canvas_box, box, new_cords=new_cords)
        main_x = start_x
        main_y = start_y
        if text is not None or self.has_back:
            overlay_image = Image.new("RGBA", canvas_box, (255, 255, 255, 0))
            drawing = ImageDraw.Draw(overlay_image)
            if self.has_back:
                cords = (
                    start_x - self.back_padding,
                    start_y - self.back_padding,
                    start_x + (back_width if self.back_box else box_width) + self.back_padding,
                    start_y + (back_height if self.back_box else box_height) + self.back_padding
                )
                if self.back_radius:
                    drawing.rounded_rectangle(cords, fill=self.back_color, outline=self.back_line_color, width=self.back_line_width, radius=self.back_radius)
                else:
                    drawing.rectangle(cords, fill=self.back_color, outline=self.back_line_color, width=self.back_line_width)

            if self.back_box:
                if self.back_align == "left":
                    main_y = start_y + (back_height - box_height) // 2
                elif self.back_align == "right":
                    main_x = start_x + back_width - (text_width if text is not None else image_width)
                elif self.back_align == "top":
                    main_x = start_x + (back_width - box_width) // 2
                elif self.back_align == "bottom":
                    main_y = start_y + back_height - (text_height if text is not None else image_height)
                else:
                    main_x = start_x + (back_width - box_width) // 2
                    main_y = start_y + (back_height - box_height) // 2

            addon_x = None
            addon_y = None
            if text is not None and image_width:
                addon_x = main_x
                addon_y = main_y
                if self.addon_position == "left":
                    if self.back_align == "left":
                        main_x = start_x + self.addon_offset
                    elif self.back_align == "right":
                        addon_x = start_x + back_width - self.addon_offset
                    else:
                        main_x = addon_x + image_width + self.addon_offset
                elif self.addon_position == "right":
                    if self.back_align == "left":
                        addon_x = start_x + self.addon_offset
                    elif self.back_align == "right":
                        addon_x = start_x + back_width - image_width
                        main_x = start_x + back_width - self.addon_offset
                    else:
                        addon_x = main_x + text_width + self.addon_offset
                elif text_width < image_width:
                    main_x = main_x + ((image_width - text_width) / 2)
                elif text_width > image_width:
                    addon_x = main_x + ((text_width - image_width) / 2)

                if self.addon_position == "top":
                    if self.back_align == "top":
                        main_y = start_y + self.addon_offset
                    elif self.back_align == "bottom":
                        addon_y = start_y + back_height - self.addon_offset
                    else:
                        main_y = addon_y + image_height + self.addon_offset
                elif self.addon_position == "bottom":
                    if self.back_align == "top":
                        addon_y = start_y + self.addon_offset
                    elif self.back_align == "bottom":
                        addon_y = start_y + back_height - image_height
                        main_y = start_y + back_height - self.addon_offset
                    else:
                        addon_y = main_y + text_height + self.addon_offset
                elif text_height < image_height:
                    main_y = main_y + ((image_height - text_height) / 2)
                elif text_height > image_height:
                    addon_y = main_y + ((text_height - image_height) / 2)

            if text is not None:
                drawing.text((int(main_x), int(main_y)), text, font=self.font, fill=self.font_color, anchor="lt")
            if addon_x is not None:
                main_x = addon_x
                main_y = addon_y
        return overlay_image, (int(main_x), int(main_y))

    def get_overlay_compare(self):
        output = f"{self.name}"
        if self.group:
            output += f"{self.group}{self.weight}"
        if self.has_coordinates():
            output += f"{self.horizontal_align}{self.horizontal_offset}{self.vertical_offset}{self.vertical_align}"
        if self.font_name:
            output += f"{self.font_name}{self.font_size}"
        if self.back_box:
            output += f"{self.back_box[0]}{self.back_box[1]}{self.back_align}"
        if self.addon_position is not None:
            output += f"{self.addon_position}{self.addon_offset}"
        for value in [self.font_color, self.back_color, self.back_radius, self.back_padding, self.back_line_color, self.back_line_width]:
            if value is not None:
                output += f"{value}"
        return output

    def has_coordinates(self):
        return self.horizontal_offset is not None and self.vertical_offset is not None

    def get_text_size(self, text):
        return ImageDraw.Draw(Image.new("RGBA", (0, 0))).textbbox((0, 0), text, font=self.font, anchor='lt')

    def get_coordinates(self, canvas_box, box, new_cords=None):
        if new_cords is None and not self.has_coordinates():
            return 0, 0
        if self.back_box:
            box = self.back_box

        def get_cord(value, image_value, over_value, align):
            value = int(image_value * 0.01 * int(value[:-1])) if str(value).endswith("%") else value
            if align in ["right", "bottom"]:
                return image_value - over_value - value
            elif align == "center":
                return int(image_value / 2) - int(over_value / 2) + value
            else:
                return value

        if new_cords is None:
            ho = self.horizontal_offset
            ha = self.horizontal_align
            vo = self.vertical_offset
            va = self.vertical_align
        else:
            ha, ho, va, vo = new_cords
        return get_cord(ho, canvas_box[0], box[0], ha), get_cord(vo, canvas_box[1], box[1], va)
