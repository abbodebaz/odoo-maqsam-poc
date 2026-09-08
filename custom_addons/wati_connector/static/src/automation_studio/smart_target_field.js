/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class WatiSmartTargetField extends Component {
    static template = "wati_connector.WatiSmartTargetField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };

    get metadata() {
        return this.props.record.data.smart_target_metadata || {
            mode: "input",
            input_type: "text",
            placeholder: this.props.placeholder || "اكتب القيمة المطلوبة",
            options: [],
        };
    }

    get currentValue() {
        const value = this.props.record.data[this.props.name];
        return value === false || value === null || value === undefined ? "" : String(value);
    }

    get options() {
        return Array.isArray(this.metadata.options) ? this.metadata.options : [];
    }

    get datalistId() {
        return `${this.props.id || "wati_smart_target"}_options`;
    }

    get placeholder() {
        return this.metadata.placeholder || this.props.placeholder || "اكتب القيمة المطلوبة";
    }

    async onValueChange(ev) {
        const value = ev.target.value;
        await this.props.record.update({
            [this.props.name]: value || false,
        });
    }
}

export const watiSmartTargetField = {
    component: WatiSmartTargetField,
    displayName: "WATI Smart Target",
    supportedTypes: ["char"],
    extractProps: ({ placeholder }) => ({ placeholder }),
};

registry.category("fields").add("wati_smart_target", watiSmartTargetField);
