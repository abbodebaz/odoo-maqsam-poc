FROM odoo:19.0

USER root

COPY custom_addons /mnt/extra-addons
COPY odoo-railway-start.sh /usr/local/bin/odoo-railway-start

RUN chown -R odoo:odoo /mnt/extra-addons \
    && chmod +x /usr/local/bin/odoo-railway-start

USER odoo

EXPOSE 8069

ENTRYPOINT ["/usr/local/bin/odoo-railway-start"]
