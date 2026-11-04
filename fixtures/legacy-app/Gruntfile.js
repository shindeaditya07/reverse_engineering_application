module.exports = function (grunt) {
  grunt.initConfig({
    shell: { deploy: { command: 'scp -r . deploy@prod.example.invalid:/srv/shopledger' } }
  });
  grunt.registerTask('deploy', ['shell:deploy']);
};
