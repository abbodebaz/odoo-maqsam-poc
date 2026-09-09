/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class WatiSmartRecipientField extends Component {
    static template = "wati_connector.WatiSmartRecipientField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };

    get metadata() {
        return this.props.record.data.smart_recipient_metadata || {
            mode: "empty",
            placeholder: this.props.placeholder || "Choose the recipient number",
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

    get placeholder() {
        return this.metadata.placeholder || this.props.placeholder || "Choose the recipient number";
    }

    async onValueChange(ev) {
        await this.props.record.update({
            [this.props.name]: ev.target.value || false,
        });
    }
}

export const watiSmartRecipientField = {
    component: WatiSmartRecipientField,
    displayName: "WATI Smart Recipient",
    supportedTypes: ["char"],
    extractProps: ({ placeholder }) => ({ placeholder }),
};

registry.category("fields").add("wati_smart_recipient", watiSmartRecipientField);
