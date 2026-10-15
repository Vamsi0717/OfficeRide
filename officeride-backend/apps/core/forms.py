from django import forms


class BootstrapFormMixin:
    """Adds Bootstrap CSS classes to every widget so forms look consistent."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.MultiWidget):
                continue  # composite widgets such as the time picker style their own parts
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f'{widget.attrs.get("class", "")} {css}'.strip()