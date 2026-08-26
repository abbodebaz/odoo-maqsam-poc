FROM odoo:19.0

USER root

COPY custom_addons /mnt/extra-addons
RUN chown -R odoo:odoo /mnt/extra-addons

USER odoo

EXPOSE 8069

CMD ["odoo", "--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons", "--proxy-mode"]
